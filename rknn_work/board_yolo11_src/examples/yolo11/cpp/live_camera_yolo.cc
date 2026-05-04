// Copyright (c) 2026.
//
// Live V4L2 NV12 camera stream for RKNN YOLO-family models.

#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <limits>
#include <string>
#include <vector>

#include "yolo11.h"
#include "image_utils.h"

#ifndef DISABLE_LIBJPEG
#include "turbojpeg.h"
#endif

namespace {

static_assert(sizeof(uint32_t) == 4, "protocol requires 32-bit uint32_t");
static_assert(sizeof(float) == 4, "protocol requires 32-bit float");

#ifndef DEFAULT_MODEL_PATH
#define DEFAULT_MODEL_PATH "model/yolo11n_rk3576.rknn"
#endif

#ifndef LIVE_APP_NAME
#define LIVE_APP_NAME "RKNN YOLO"
#endif

#ifndef DEFAULT_DEVICE_PATH
#define DEFAULT_DEVICE_PATH "/dev/video42"
#endif

#ifndef DEFAULT_CAMERA_WIDTH
#define DEFAULT_CAMERA_WIDTH 960
#endif

#ifndef DEFAULT_CAMERA_HEIGHT
#define DEFAULT_CAMERA_HEIGHT 540
#endif

#ifndef DEFAULT_CAMERA_FPS
#define DEFAULT_CAMERA_FPS 8
#endif

#ifndef DEFAULT_CAMERA_SKIP
#define DEFAULT_CAMERA_SKIP 8
#endif

#ifndef DEFAULT_CAMERA_FORMAT
#define DEFAULT_CAMERA_FORMAT "yuyv"
#endif

const char kDefaultModel[] = DEFAULT_MODEL_PATH;
const char kDefaultDevice[] = DEFAULT_DEVICE_PATH;
const char kDefaultFormat[] = DEFAULT_CAMERA_FORMAT;
const uint32_t kDefaultWidth = DEFAULT_CAMERA_WIDTH;
const uint32_t kDefaultHeight = DEFAULT_CAMERA_HEIGHT;
const uint32_t kDefaultFps = DEFAULT_CAMERA_FPS;
const uint32_t kDefaultFrames = 0;
const uint32_t kDefaultSkip = DEFAULT_CAMERA_SKIP;
const uint32_t kDefaultBuffers = 4;
const float kDefaultConfThreshold = BOX_THRESH;
const float kDefaultNmsThreshold = NMS_THRESH;
const uint32_t kMaxPayloadSize = std::numeric_limits<uint32_t>::max();
const char kProtocolMagic[] = "RYL1";

enum CameraInputFormat {
    CAMERA_INPUT_NV12,
    CAMERA_INPUT_YUYV,
    CAMERA_INPUT_MJPEG,
};

struct Options {
    std::string model;
    std::string device;
    std::string format;
    uint32_t width;
    uint32_t height;
    uint32_t fps;
    uint32_t frames;
    uint32_t skip;
    uint32_t buffers;
    bool roi_enabled;
    uint32_t roi_x;
    uint32_t roi_y;
    uint32_t roi_w;
    uint32_t roi_h;
    float conf_threshold;
    float nms_threshold;

    Options()
        : model(kDefaultModel),
          device(kDefaultDevice),
          format(kDefaultFormat),
          width(kDefaultWidth),
          height(kDefaultHeight),
          fps(kDefaultFps),
          frames(kDefaultFrames),
          skip(kDefaultSkip),
          buffers(kDefaultBuffers),
          roi_enabled(false),
          roi_x(0),
          roi_y(0),
          roi_w(0),
          roi_h(0),
          conf_threshold(kDefaultConfThreshold),
          nms_threshold(kDefaultNmsThreshold) {}
};

struct MappedPlane {
    void *start;
    size_t length;

    MappedPlane() : start(NULL), length(0) {}
};

struct CameraBuffer {
    std::vector<MappedPlane> planes;
};

struct CameraContext {
    int fd;
    enum v4l2_buf_type buffer_type;
    CameraInputFormat input_format;
    uint32_t width;
    uint32_t height;
    uint32_t num_planes;
    size_t y_stride;
    size_t uv_stride;
    size_t yuyv_stride;
    std::vector<CameraBuffer> buffers;

    CameraContext()
        : fd(-1),
          buffer_type(V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE),
          input_format(CAMERA_INPUT_NV12),
          width(0),
          height(0),
          num_planes(0),
          y_stride(0),
          uv_stride(0),
          yuyv_stride(0) {}
};

static int xioctl(int fd, unsigned long request, void *arg)
{
    int ret;
    do {
        ret = ioctl(fd, request, arg);
    } while (ret == -1 && errno == EINTR);
    return ret;
}

static std::string fourcc_to_string(uint32_t fourcc)
{
    char text[5];
    text[0] = static_cast<char>(fourcc & 0xff);
    text[1] = static_cast<char>((fourcc >> 8) & 0xff);
    text[2] = static_cast<char>((fourcc >> 16) & 0xff);
    text[3] = static_cast<char>((fourcc >> 24) & 0xff);
    text[4] = '\0';
    return std::string(text);
}

static const char *camera_input_format_name(CameraInputFormat format)
{
    switch (format) {
    case CAMERA_INPUT_NV12:
        return "NV12";
    case CAMERA_INPUT_YUYV:
        return "YUYV";
    case CAMERA_INPUT_MJPEG:
        return "MJPG";
    }
    return "UNKNOWN";
}

static void print_usage(const char *prog)
{
    fprintf(stderr,
            "Usage: %s [--model PATH] [--device NODE] [--format yuyv|mjpg] [--width N] [--height N] "
            "[--fps N] [--frames N] [--skip N] [--buffers N] [--roi X,Y,W,H] [--conf F] [--nms F]\n"
            "Defaults: --model %s --device %s --format %s --width %u --height %u "
            "--fps %u --frames %u --skip %u --buffers %u --conf %.3f --nms %.3f\n",
            prog, kDefaultModel, kDefaultDevice, kDefaultFormat, kDefaultWidth, kDefaultHeight,
            kDefaultFps, kDefaultFrames, kDefaultSkip, kDefaultBuffers,
            kDefaultConfThreshold, kDefaultNmsThreshold);
}

static bool parse_u32(const char *text, uint32_t *value)
{
    if (text == NULL || text[0] == '\0') {
        return false;
    }

    errno = 0;
    char *end = NULL;
    unsigned long parsed = strtoul(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' ||
        parsed > std::numeric_limits<uint32_t>::max()) {
        return false;
    }

    *value = static_cast<uint32_t>(parsed);
    return true;
}

static bool parse_float_threshold(const char *text, float *value)
{
    if (text == NULL || text[0] == '\0') {
        return false;
    }

    errno = 0;
    char *end = NULL;
    float parsed = strtof(text, &end);
    if (errno != 0 || end == text || *end != '\0' || parsed <= 0.0f || parsed >= 1.0f) {
        return false;
    }

    *value = parsed;
    return true;
}

static bool parse_roi(const char *text, uint32_t *x, uint32_t *y, uint32_t *w, uint32_t *h)
{
    uint32_t values[4];
    const char *cursor = text;
    for (int i = 0; i < 4; ++i) {
        if (cursor == NULL || *cursor == '\0') {
            return false;
        }

        errno = 0;
        char *end = NULL;
        unsigned long parsed = strtoul(cursor, &end, 10);
        if (errno != 0 || end == cursor || parsed > std::numeric_limits<uint32_t>::max()) {
            return false;
        }
        values[i] = static_cast<uint32_t>(parsed);

        if (i < 3) {
            if (*end != ',') {
                return false;
            }
            cursor = end + 1;
        } else if (*end != '\0') {
            return false;
        }
    }

    if (values[2] == 0 || values[3] == 0) {
        return false;
    }

    *x = values[0];
    *y = values[1];
    *w = values[2];
    *h = values[3];
    return true;
}

static bool take_option_value(int argc, char **argv, int *index, const char *name, std::string *value);

static bool parse_roi_option(int argc, char **argv, int *index, Options *opts)
{
    std::string text;
    if (!take_option_value(argc, argv, index, "--roi", &text)) {
        return false;
    }

    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t w = 0;
    uint32_t h = 0;
    if (!parse_roi(text.c_str(), &x, &y, &w, &h)) {
        fprintf(stderr, "invalid value for --roi: %s; expected X,Y,W,H\n", text.c_str());
        return false;
    }

    opts->roi_enabled = true;
    opts->roi_x = x;
    opts->roi_y = y;
    opts->roi_w = w;
    opts->roi_h = h;
    return true;
}

static bool take_option_value(int argc, char **argv, int *index, const char *name, std::string *value)
{
    const std::string arg(argv[*index]);
    const std::string opt(name);
    const std::string prefix = opt + "=";

    if (arg == opt) {
        if (*index + 1 >= argc) {
            fprintf(stderr, "%s requires a value\n", name);
            return false;
        }
        *value = argv[++(*index)];
        return true;
    }

    if (arg.compare(0, prefix.size(), prefix) == 0) {
        *value = arg.substr(prefix.size());
        if (value->empty()) {
            fprintf(stderr, "%s requires a value\n", name);
            return false;
        }
        return true;
    }

    return false;
}

static bool parse_numeric_option(int argc, char **argv, int *index, const char *name, uint32_t *value)
{
    std::string text;
    if (!take_option_value(argc, argv, index, name, &text)) {
        return false;
    }
    if (!parse_u32(text.c_str(), value)) {
        fprintf(stderr, "invalid value for %s: %s\n", name, text.c_str());
        return false;
    }
    return true;
}

static bool parse_float_option(int argc, char **argv, int *index, const char *name, float *value)
{
    std::string text;
    if (!take_option_value(argc, argv, index, name, &text)) {
        return false;
    }
    if (!parse_float_threshold(text.c_str(), value)) {
        fprintf(stderr, "invalid value for %s: %s; expected 0.0 < value < 1.0\n",
                name, text.c_str());
        return false;
    }
    return true;
}

static bool parse_args(int argc, char **argv, Options *opts)
{
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            return false;
        }

        if (arg == "--model" || arg.compare(0, 8, "--model=") == 0) {
            if (!take_option_value(argc, argv, &i, "--model", &opts->model)) {
                return false;
            }
        } else if (arg == "--device" || arg.compare(0, 9, "--device=") == 0) {
            if (!take_option_value(argc, argv, &i, "--device", &opts->device)) {
                return false;
            }
        } else if (arg == "--format" || arg.compare(0, 9, "--format=") == 0) {
            if (!take_option_value(argc, argv, &i, "--format", &opts->format)) {
                return false;
            }
        } else if (arg == "--width" || arg.compare(0, 8, "--width=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--width", &opts->width)) {
                return false;
            }
        } else if (arg == "--height" || arg.compare(0, 9, "--height=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--height", &opts->height)) {
                return false;
            }
        } else if (arg == "--fps" || arg.compare(0, 6, "--fps=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--fps", &opts->fps)) {
                return false;
            }
        } else if (arg == "--frames" || arg.compare(0, 9, "--frames=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--frames", &opts->frames)) {
                return false;
            }
        } else if (arg == "--skip" || arg.compare(0, 7, "--skip=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--skip", &opts->skip)) {
                return false;
            }
        } else if (arg == "--buffers" || arg.compare(0, 10, "--buffers=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--buffers", &opts->buffers)) {
                return false;
            }
        } else if (arg == "--roi" || arg.compare(0, 6, "--roi=") == 0) {
            if (!parse_roi_option(argc, argv, &i, opts)) {
                return false;
            }
        } else if (arg == "--conf" || arg.compare(0, 7, "--conf=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--conf", &opts->conf_threshold)) {
                return false;
            }
        } else if (arg == "--nms" || arg.compare(0, 6, "--nms=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--nms", &opts->nms_threshold)) {
                return false;
            }
        } else {
            fprintf(stderr, "unknown argument: %s\n", arg.c_str());
            print_usage(argv[0]);
            return false;
        }
    }

    if (opts->model.empty()) {
        fprintf(stderr, "--model must not be empty\n");
        return false;
    }
    if (opts->device.empty()) {
        fprintf(stderr, "--device must not be empty\n");
        return false;
    }
    if (opts->format == "jpeg") {
        opts->format = "mjpg";
    }
    if (opts->format != "yuyv" && opts->format != "mjpg") {
        fprintf(stderr, "--format must be yuyv or mjpg, got: %s\n", opts->format.c_str());
        return false;
    }
    if (opts->width == 0 || opts->height == 0 || opts->fps == 0 || opts->buffers == 0) {
        fprintf(stderr, "--width, --height, --fps, and --buffers must be greater than zero\n");
        return false;
    }
    if ((opts->width % 16) != 0) {
        fprintf(stderr, "invalid width %u: width must be 16-aligned for RGA/NV12 input\n", opts->width);
        return false;
    }
    if ((opts->height % 2) != 0) {
        fprintf(stderr, "invalid height %u: height must be even for NV12 input\n", opts->height);
        return false;
    }

    const uint64_t payload_size = static_cast<uint64_t>(opts->width) * opts->height * 3 / 2;
    if (payload_size > kMaxPayloadSize ||
        payload_size > static_cast<uint64_t>(std::numeric_limits<int>::max())) {
        fprintf(stderr, "frame payload is too large: %llu bytes\n",
                static_cast<unsigned long long>(payload_size));
        return false;
    }

    return true;
}

static void close_camera(CameraContext *cam)
{
    for (size_t i = 0; i < cam->buffers.size(); ++i) {
        for (size_t p = 0; p < cam->buffers[i].planes.size(); ++p) {
            MappedPlane &plane = cam->buffers[i].planes[p];
            if (plane.start != NULL && plane.length > 0) {
                munmap(plane.start, plane.length);
                plane.start = NULL;
                plane.length = 0;
            }
        }
    }
    cam->buffers.clear();

    if (cam->fd >= 0) {
        close(cam->fd);
        cam->fd = -1;
    }
}

static bool queue_buffer(CameraContext *cam, uint32_t index)
{
    struct v4l2_buffer buf;
    struct v4l2_plane planes[VIDEO_MAX_PLANES];
    memset(&buf, 0, sizeof(buf));
    memset(planes, 0, sizeof(planes));

    buf.type = cam->buffer_type;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.index = index;
    if (cam->buffer_type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE) {
        buf.length = cam->num_planes;
        buf.m.planes = planes;
    }

    if (xioctl(cam->fd, VIDIOC_QBUF, &buf) < 0) {
        fprintf(stderr, "VIDIOC_QBUF index=%u failed: %s\n", index, strerror(errno));
        return false;
    }
    return true;
}

static bool open_camera(const Options &opts, CameraContext *cam)
{
    cam->fd = open(opts.device.c_str(), O_RDWR | O_NONBLOCK, 0);
    if (cam->fd < 0) {
        fprintf(stderr, "open %s failed: %s\n", opts.device.c_str(), strerror(errno));
        return false;
    }

    struct v4l2_capability cap;
    memset(&cap, 0, sizeof(cap));
    if (xioctl(cam->fd, VIDIOC_QUERYCAP, &cap) < 0) {
        fprintf(stderr, "VIDIOC_QUERYCAP failed: %s\n", strerror(errno));
        return false;
    }

    uint32_t caps = cap.capabilities;
    if ((cap.capabilities & V4L2_CAP_DEVICE_CAPS) != 0) {
        caps = cap.device_caps;
    }
    const bool is_mplane_capture = (caps & V4L2_CAP_VIDEO_CAPTURE_MPLANE) != 0;
    const bool is_single_capture = (caps & V4L2_CAP_VIDEO_CAPTURE) != 0;
    if (!is_mplane_capture && !is_single_capture) {
        fprintf(stderr, "%s is not a V4L2 capture device\n", opts.device.c_str());
        return false;
    }
    if ((caps & V4L2_CAP_STREAMING) == 0) {
        fprintf(stderr, "%s does not support streaming I/O\n", opts.device.c_str());
        return false;
    }

    if (is_mplane_capture) {
        struct v4l2_format fmt;
        memset(&fmt, 0, sizeof(fmt));
        fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        fmt.fmt.pix_mp.width = opts.width;
        fmt.fmt.pix_mp.height = opts.height;
        fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12;
        fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;

        if (xioctl(cam->fd, VIDIOC_S_FMT, &fmt) < 0) {
            fprintf(stderr, "VIDIOC_S_FMT %ux%u NV12 failed: %s\n",
                    opts.width, opts.height, strerror(errno));
            return false;
        }

        if (fmt.fmt.pix_mp.width != opts.width || fmt.fmt.pix_mp.height != opts.height) {
            fprintf(stderr, "camera changed format to %ux%u; requested %ux%u\n",
                    fmt.fmt.pix_mp.width, fmt.fmt.pix_mp.height, opts.width, opts.height);
            return false;
        }
        if (fmt.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_NV12) {
            fprintf(stderr, "camera returned %s; expected NV12\n",
                    fourcc_to_string(fmt.fmt.pix_mp.pixelformat).c_str());
            return false;
        }
        if (fmt.fmt.pix_mp.num_planes == 0 || fmt.fmt.pix_mp.num_planes > VIDEO_MAX_PLANES) {
            fprintf(stderr, "invalid plane count from camera: %u\n", fmt.fmt.pix_mp.num_planes);
            return false;
        }

        cam->buffer_type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        cam->input_format = CAMERA_INPUT_NV12;
        cam->width = fmt.fmt.pix_mp.width;
        cam->height = fmt.fmt.pix_mp.height;
        cam->num_planes = fmt.fmt.pix_mp.num_planes;
        cam->y_stride = fmt.fmt.pix_mp.plane_fmt[0].bytesperline;
        if (cam->y_stride == 0) {
            cam->y_stride = cam->width;
        }
        if (cam->num_planes > 1) {
            cam->uv_stride = fmt.fmt.pix_mp.plane_fmt[1].bytesperline;
            if (cam->uv_stride == 0) {
                cam->uv_stride = cam->width;
            }
        } else {
            cam->uv_stride = cam->y_stride;
        }
        if (cam->y_stride < cam->width || cam->uv_stride < cam->width) {
            fprintf(stderr, "invalid strides from camera: y=%zu uv=%zu width=%u\n",
                    cam->y_stride, cam->uv_stride, cam->width);
            return false;
        }
        if (cam->num_planes > 2) {
            fprintf(stderr, "unsupported NV12 plane count: %u\n", cam->num_planes);
            return false;
        }
    } else {
        const bool use_mjpeg = opts.format == "mjpg";
        const uint32_t requested_fourcc = use_mjpeg ? V4L2_PIX_FMT_MJPEG : V4L2_PIX_FMT_YUYV;
        const char *requested_name = use_mjpeg ? "MJPG" : "YUYV";
        struct v4l2_format fmt;
        memset(&fmt, 0, sizeof(fmt));
        fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        fmt.fmt.pix.width = opts.width;
        fmt.fmt.pix.height = opts.height;
        fmt.fmt.pix.pixelformat = requested_fourcc;
        fmt.fmt.pix.field = V4L2_FIELD_NONE;

        if (xioctl(cam->fd, VIDIOC_S_FMT, &fmt) < 0) {
            fprintf(stderr, "VIDIOC_S_FMT %ux%u %s failed: %s\n",
                    opts.width, opts.height, requested_name, strerror(errno));
            return false;
        }
        if (fmt.fmt.pix.width != opts.width || fmt.fmt.pix.height != opts.height) {
            fprintf(stderr, "camera changed format to %ux%u; requested %ux%u\n",
                    fmt.fmt.pix.width, fmt.fmt.pix.height, opts.width, opts.height);
            return false;
        }
        if (fmt.fmt.pix.pixelformat != requested_fourcc) {
            fprintf(stderr, "camera returned %s; expected %s\n",
                    fourcc_to_string(fmt.fmt.pix.pixelformat).c_str(), requested_name);
            return false;
        }

        cam->buffer_type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        cam->input_format = use_mjpeg ? CAMERA_INPUT_MJPEG : CAMERA_INPUT_YUYV;
        cam->width = fmt.fmt.pix.width;
        cam->height = fmt.fmt.pix.height;
        cam->num_planes = 1;
        if (use_mjpeg) {
            cam->yuyv_stride = 0;
        } else {
            cam->yuyv_stride = fmt.fmt.pix.bytesperline;
            if (cam->yuyv_stride == 0) {
                cam->yuyv_stride = cam->width * 2;
            }
            if (cam->yuyv_stride < cam->width * 2) {
                fprintf(stderr, "invalid YUYV stride: stride=%zu width=%u\n",
                        cam->yuyv_stride, cam->width);
                return false;
            }
        }
    }

    struct v4l2_streamparm parm;
    memset(&parm, 0, sizeof(parm));
    parm.type = cam->buffer_type;
    parm.parm.capture.timeperframe.numerator = 1;
    parm.parm.capture.timeperframe.denominator = opts.fps;
    if (xioctl(cam->fd, VIDIOC_S_PARM, &parm) < 0) {
        fprintf(stderr, "warning: VIDIOC_S_PARM fps=%u failed: %s\n", opts.fps, strerror(errno));
    }

    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = opts.buffers;
    req.type = cam->buffer_type;
    req.memory = V4L2_MEMORY_MMAP;

    if (xioctl(cam->fd, VIDIOC_REQBUFS, &req) < 0) {
        fprintf(stderr, "VIDIOC_REQBUFS count=%u failed: %s\n", opts.buffers, strerror(errno));
        return false;
    }
    if (req.count < 2) {
        fprintf(stderr, "insufficient mmap buffers: requested %u got %u\n", opts.buffers, req.count);
        return false;
    }

    cam->buffers.resize(req.count);
    for (uint32_t i = 0; i < req.count; ++i) {
        struct v4l2_buffer buf;
        struct v4l2_plane planes[VIDEO_MAX_PLANES];
        memset(&buf, 0, sizeof(buf));
        memset(planes, 0, sizeof(planes));

        buf.type = cam->buffer_type;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (cam->buffer_type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE) {
            buf.length = cam->num_planes;
            buf.m.planes = planes;
        }

        if (xioctl(cam->fd, VIDIOC_QUERYBUF, &buf) < 0) {
            fprintf(stderr, "VIDIOC_QUERYBUF index=%u failed: %s\n", i, strerror(errno));
            return false;
        }

        if (cam->buffer_type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE) {
            cam->buffers[i].planes.resize(cam->num_planes);
            for (uint32_t p = 0; p < cam->num_planes; ++p) {
                if (planes[p].length == 0) {
                    fprintf(stderr, "buffer %u plane %u has zero length\n", i, p);
                    return false;
                }
                void *addr = mmap(NULL, planes[p].length, PROT_READ | PROT_WRITE, MAP_SHARED,
                                  cam->fd, planes[p].m.mem_offset);
                if (addr == MAP_FAILED) {
                    fprintf(stderr, "mmap buffer %u plane %u failed: %s\n", i, p, strerror(errno));
                    return false;
                }
                cam->buffers[i].planes[p].start = addr;
                cam->buffers[i].planes[p].length = planes[p].length;
            }
        } else {
            if (buf.length == 0) {
                fprintf(stderr, "buffer %u has zero length\n", i);
                return false;
            }
            void *addr = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED,
                              cam->fd, buf.m.offset);
            if (addr == MAP_FAILED) {
                fprintf(stderr, "mmap buffer %u failed: %s\n", i, strerror(errno));
                return false;
            }
            cam->buffers[i].planes.resize(1);
            cam->buffers[i].planes[0].start = addr;
            cam->buffers[i].planes[0].length = buf.length;
        }
    }

    for (uint32_t i = 0; i < req.count; ++i) {
        if (!queue_buffer(cam, i)) {
            return false;
        }
    }

    fprintf(stderr, "camera %s configured: %ux%u %s, fps=%u, buffers=%u, planes=%u\n",
            opts.device.c_str(), cam->width, cam->height,
            camera_input_format_name(cam->input_format),
            opts.fps, req.count, cam->num_planes);
    return true;
}

static bool start_camera(CameraContext *cam)
{
    enum v4l2_buf_type type = cam->buffer_type;
    if (xioctl(cam->fd, VIDIOC_STREAMON, &type) < 0) {
        fprintf(stderr, "VIDIOC_STREAMON failed: %s\n", strerror(errno));
        return false;
    }
    return true;
}

static void stop_camera(CameraContext *cam)
{
    if (cam->fd < 0) {
        return;
    }
    enum v4l2_buf_type type = cam->buffer_type;
    if (xioctl(cam->fd, VIDIOC_STREAMOFF, &type) < 0) {
        fprintf(stderr, "warning: VIDIOC_STREAMOFF failed: %s\n", strerror(errno));
    }
}

static bool dequeue_buffer(CameraContext *cam, struct v4l2_buffer *buf, struct v4l2_plane planes[VIDEO_MAX_PLANES])
{
    for (;;) {
        struct pollfd pfd;
        memset(&pfd, 0, sizeof(pfd));
        pfd.fd = cam->fd;
        pfd.events = POLLIN | POLLERR;

        int poll_ret;
        do {
            poll_ret = poll(&pfd, 1, 2000);
        } while (poll_ret < 0 && errno == EINTR);

        if (poll_ret == 0) {
            fprintf(stderr, "camera dequeue timeout\n");
            return false;
        }
        if (poll_ret < 0) {
            fprintf(stderr, "poll failed: %s\n", strerror(errno));
            return false;
        }

        memset(buf, 0, sizeof(*buf));
        memset(planes, 0, sizeof(struct v4l2_plane) * VIDEO_MAX_PLANES);
        buf->type = cam->buffer_type;
        buf->memory = V4L2_MEMORY_MMAP;
        if (cam->buffer_type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE) {
            buf->length = cam->num_planes;
            buf->m.planes = planes;
        }

        if (xioctl(cam->fd, VIDIOC_DQBUF, buf) == 0) {
            if (buf->index >= cam->buffers.size()) {
                fprintf(stderr, "camera returned invalid buffer index %u\n", buf->index);
                return false;
            }
            return true;
        }
        if (errno == EAGAIN) {
            continue;
        }

        fprintf(stderr, "VIDIOC_DQBUF failed: %s\n", strerror(errno));
        return false;
    }
}

static size_t available_plane_bytes(const MappedPlane &mapped, const struct v4l2_plane &plane)
{
    if (plane.data_offset >= mapped.length) {
        return 0;
    }

    size_t available = mapped.length - plane.data_offset;
    if (plane.bytesused > plane.data_offset) {
        const size_t used = plane.bytesused - plane.data_offset;
        if (used < available) {
            available = used;
        }
    }
    return available;
}

static bool copy_plane_rows(const uint8_t *src, size_t src_len, uint32_t rows,
                            uint32_t row_bytes, size_t stride, uint8_t *dst)
{
    if (stride < row_bytes) {
        fprintf(stderr, "invalid row stride: stride=%zu row=%u\n", stride, row_bytes);
        return false;
    }
    if (rows == 0) {
        return true;
    }

    const uint64_t needed = static_cast<uint64_t>(rows - 1) * stride + row_bytes;
    if (needed > src_len) {
        fprintf(stderr, "short V4L2 plane: need %llu bytes, have %zu\n",
                static_cast<unsigned long long>(needed), src_len);
        return false;
    }

    for (uint32_t row = 0; row < rows; ++row) {
        memcpy(dst + static_cast<size_t>(row) * row_bytes, src + static_cast<size_t>(row) * stride, row_bytes);
    }
    return true;
}

static bool copy_nv12_frame(const CameraContext &cam, const struct v4l2_buffer &buf,
                            const struct v4l2_plane planes[VIDEO_MAX_PLANES],
                            std::vector<uint8_t> *out)
{
    const size_t y_size = static_cast<size_t>(cam.width) * cam.height;
    const size_t frame_size = y_size * 3 / 2;
    out->resize(frame_size);

    const CameraBuffer &buffer = cam.buffers[buf.index];
    if (cam.num_planes == 1) {
        const MappedPlane &mapped = buffer.planes[0];
        const struct v4l2_plane &plane = planes[0];
        const size_t available = available_plane_bytes(mapped, plane);
        const uint8_t *base = static_cast<const uint8_t *>(mapped.start) + plane.data_offset;
        const size_t uv_offset = cam.y_stride * cam.height;

        if (!copy_plane_rows(base, available, cam.height, cam.width, cam.y_stride, out->data())) {
            return false;
        }
        if (uv_offset > available) {
            fprintf(stderr, "short V4L2 NV12 buffer: uv offset %zu exceeds %zu\n", uv_offset, available);
            return false;
        }
        return copy_plane_rows(base + uv_offset, available - uv_offset, cam.height / 2, cam.width,
                               cam.uv_stride, out->data() + y_size);
    }

    const MappedPlane &mapped_y = buffer.planes[0];
    const MappedPlane &mapped_uv = buffer.planes[1];
    const struct v4l2_plane &plane_y = planes[0];
    const struct v4l2_plane &plane_uv = planes[1];
    const size_t y_available = available_plane_bytes(mapped_y, plane_y);
    const size_t uv_available = available_plane_bytes(mapped_uv, plane_uv);
    const uint8_t *src_y = static_cast<const uint8_t *>(mapped_y.start) + plane_y.data_offset;
    const uint8_t *src_uv = static_cast<const uint8_t *>(mapped_uv.start) + plane_uv.data_offset;

    if (!copy_plane_rows(src_y, y_available, cam.height, cam.width, cam.y_stride, out->data())) {
        return false;
    }
    return copy_plane_rows(src_uv, uv_available, cam.height / 2, cam.width,
                           cam.uv_stride, out->data() + y_size);
}

static uint8_t clamp_u8(int value)
{
    if (value < 0) {
        return 0;
    }
    if (value > 255) {
        return 255;
    }
    return static_cast<uint8_t>(value);
}

static void yuv_to_rgb(uint8_t y, uint8_t u, uint8_t v, uint8_t *rgb)
{
    const int c = static_cast<int>(y) - 16;
    const int d = static_cast<int>(u) - 128;
    const int e = static_cast<int>(v) - 128;
    rgb[0] = clamp_u8((298 * c + 409 * e + 128) >> 8);
    rgb[1] = clamp_u8((298 * c - 100 * d - 208 * e + 128) >> 8);
    rgb[2] = clamp_u8((298 * c + 516 * d + 128) >> 8);
}

static bool copy_yuyv_frame(const CameraContext &cam, const struct v4l2_buffer &buf,
                            std::vector<uint8_t> *rgb_out, std::vector<uint8_t> *nv12_out)
{
    if (buf.index >= cam.buffers.size() || cam.buffers[buf.index].planes.empty()) {
        fprintf(stderr, "invalid YUYV buffer index %u\n", buf.index);
        return false;
    }

    const MappedPlane &mapped = cam.buffers[buf.index].planes[0];
    size_t available = mapped.length;
    if (buf.bytesused > 0 && buf.bytesused < available) {
        available = buf.bytesused;
    }
    const uint64_t needed = static_cast<uint64_t>(cam.height - 1) * cam.yuyv_stride + cam.width * 2;
    if (needed > available) {
        fprintf(stderr, "short YUYV buffer: need %llu bytes, have %zu\n",
                static_cast<unsigned long long>(needed), available);
        return false;
    }

    const size_t pixel_count = static_cast<size_t>(cam.width) * cam.height;
    rgb_out->resize(pixel_count * 3);
    nv12_out->resize(pixel_count * 3 / 2);
    uint8_t *rgb = rgb_out->data();
    uint8_t *nv12 = nv12_out->data();
    uint8_t *nv12_uv = nv12 + pixel_count;
    const uint8_t *base = static_cast<const uint8_t *>(mapped.start);

    for (uint32_t row = 0; row < cam.height; ++row) {
        const uint8_t *src = base + static_cast<size_t>(row) * cam.yuyv_stride;
        uint8_t *dst_y = nv12 + static_cast<size_t>(row) * cam.width;
        uint8_t *dst_rgb = rgb + static_cast<size_t>(row) * cam.width * 3;

        for (uint32_t col = 0; col < cam.width; col += 2) {
            const uint8_t y0 = src[col * 2 + 0];
            const uint8_t u = src[col * 2 + 1];
            const uint8_t y1 = src[col * 2 + 2];
            const uint8_t v = src[col * 2 + 3];

            dst_y[col] = y0;
            dst_y[col + 1] = y1;
            yuv_to_rgb(y0, u, v, dst_rgb + col * 3);
            yuv_to_rgb(y1, u, v, dst_rgb + (col + 1) * 3);

            if ((row % 2) == 0) {
                const size_t uv_offset = static_cast<size_t>(row / 2) * cam.width + col;
                nv12_uv[uv_offset] = u;
                nv12_uv[uv_offset + 1] = v;
            }
        }
    }

    return true;
}

static void rgb_to_nv12(const uint8_t *rgb, uint32_t width, uint32_t height,
                        std::vector<uint8_t> *nv12_out)
{
    const size_t pixel_count = static_cast<size_t>(width) * height;
    nv12_out->resize(pixel_count * 3 / 2);
    uint8_t *nv12 = nv12_out->data();
    uint8_t *uv = nv12 + pixel_count;

    for (uint32_t row = 0; row < height; ++row) {
        for (uint32_t col = 0; col < width; ++col) {
            const uint8_t *p = rgb + (static_cast<size_t>(row) * width + col) * 3;
            const int r = p[0];
            const int g = p[1];
            const int b = p[2];
            const int y = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16;
            nv12[static_cast<size_t>(row) * width + col] = clamp_u8(y);
        }
    }

    for (uint32_t row = 0; row < height; row += 2) {
        for (uint32_t col = 0; col < width; col += 2) {
            int r_sum = 0;
            int g_sum = 0;
            int b_sum = 0;
            for (uint32_t dy = 0; dy < 2; ++dy) {
                for (uint32_t dx = 0; dx < 2; ++dx) {
                    const uint8_t *p = rgb + (static_cast<size_t>(row + dy) * width + (col + dx)) * 3;
                    r_sum += p[0];
                    g_sum += p[1];
                    b_sum += p[2];
                }
            }
            const int r = r_sum / 4;
            const int g = g_sum / 4;
            const int b = b_sum / 4;
            const int u = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
            const int v = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
            const size_t uv_offset = static_cast<size_t>(row / 2) * width + col;
            uv[uv_offset] = clamp_u8(u);
            uv[uv_offset + 1] = clamp_u8(v);
        }
    }
}

static bool copy_mjpeg_frame(const CameraContext &cam, const struct v4l2_buffer &buf,
                             std::vector<uint8_t> *rgb_out, std::vector<uint8_t> *nv12_out,
                             image_buffer_t *image)
{
#ifdef DISABLE_LIBJPEG
    (void)cam;
    (void)buf;
    (void)rgb_out;
    (void)nv12_out;
    (void)image;
    fprintf(stderr, "MJPG input requires libjpeg-turbo support\n");
    return false;
#else
    if (buf.index >= cam.buffers.size() || cam.buffers[buf.index].planes.empty()) {
        fprintf(stderr, "invalid MJPG buffer index %u\n", buf.index);
        return false;
    }

    const MappedPlane &mapped = cam.buffers[buf.index].planes[0];
    size_t jpeg_size = buf.bytesused;
    if (jpeg_size == 0 || jpeg_size > mapped.length) {
        jpeg_size = mapped.length;
    }
    if (jpeg_size < 4) {
        fprintf(stderr, "short MJPG buffer: %zu bytes\n", jpeg_size);
        return false;
    }

    const unsigned char *jpeg = static_cast<const unsigned char *>(mapped.start);
    size_t jpeg_offset = 0;
    while (jpeg_offset + 1 < jpeg_size &&
           !(jpeg[jpeg_offset] == 0xff && jpeg[jpeg_offset + 1] == 0xd8)) {
        ++jpeg_offset;
    }
    if (jpeg_offset + 1 >= jpeg_size) {
        fprintf(stderr, "MJPG buffer does not contain JPEG SOI marker, first bytes: 0x%02x 0x%02x\n",
                jpeg[0], jpeg[1]);
        return false;
    }
    if (jpeg_offset > 0) {
        fprintf(stderr, "MJPG buffer has %zu leading non-JPEG bytes; resyncing\n", jpeg_offset);
        jpeg += jpeg_offset;
        jpeg_size -= jpeg_offset;
    }

    tjhandle handle = tjInitDecompress();
    if (handle == NULL) {
        fprintf(stderr, "tjInitDecompress failed\n");
        return false;
    }

    int width = 0;
    int height = 0;
    int subsample = 0;
    int colorspace = 0;
    int ret = tjDecompressHeader3(handle, jpeg, static_cast<unsigned long>(jpeg_size),
                                  &width, &height, &subsample, &colorspace);
    if (ret < 0 || width <= 0 || height <= 0) {
        fprintf(stderr, "MJPG header decode failed: %s\n", tjGetErrorStr());
        tjDestroy(handle);
        return false;
    }
    if ((width % 2) != 0 || (height % 2) != 0) {
        fprintf(stderr, "MJPG frame size must be even for NV12 payload, got %dx%d\n", width, height);
        tjDestroy(handle);
        return false;
    }

    const size_t rgb_size = static_cast<size_t>(width) * height * 3;
    if (rgb_size > static_cast<size_t>(std::numeric_limits<int>::max())) {
        fprintf(stderr, "MJPG decoded frame too large: %dx%d\n", width, height);
        tjDestroy(handle);
        return false;
    }

    rgb_out->resize(rgb_size);
    ret = tjDecompress2(handle, jpeg, static_cast<unsigned long>(jpeg_size), rgb_out->data(),
                        width, 0, height, TJPF_RGB, 0);
    if (ret < 0) {
        fprintf(stderr, "MJPG decompress failed: %s\n", tjGetErrorStr());
        tjDestroy(handle);
        return false;
    }
    tjDestroy(handle);

    rgb_to_nv12(rgb_out->data(), static_cast<uint32_t>(width), static_cast<uint32_t>(height), nv12_out);

    image->width = width;
    image->height = height;
    image->width_stride = width;
    image->height_stride = height;
    image->format = IMAGE_FORMAT_RGB888;
    image->virt_addr = rgb_out->data();
    image->size = static_cast<int>(rgb_out->size());
    return true;
#endif
}

static bool write_all(int fd, const void *data, size_t size)
{
    const uint8_t *ptr = static_cast<const uint8_t *>(data);
    size_t written = 0;
    while (written < size) {
        ssize_t ret = write(fd, ptr + written, size - written);
        if (ret < 0) {
            if (errno == EINTR) {
                continue;
            }
            return false;
        }
        if (ret == 0) {
            return false;
        }
        written += static_cast<size_t>(ret);
    }
    return true;
}

static void append_u32_le(std::vector<uint8_t> *out, uint32_t value)
{
    out->push_back(static_cast<uint8_t>(value & 0xff));
    out->push_back(static_cast<uint8_t>((value >> 8) & 0xff));
    out->push_back(static_cast<uint8_t>((value >> 16) & 0xff));
    out->push_back(static_cast<uint8_t>((value >> 24) & 0xff));
}

static void append_f32_le(std::vector<uint8_t> *out, float value)
{
    uint32_t bits = 0;
    memcpy(&bits, &value, sizeof(bits));
    append_u32_le(out, bits);
}

static bool write_frame_packet(int stream_fd, uint32_t width, uint32_t height, uint32_t frame_index,
                               const object_detect_result_list &results,
                               const std::vector<uint8_t> &frame)
{
    uint32_t det_count = 0;
    if (results.count > 0) {
        det_count = static_cast<uint32_t>(results.count);
        if (det_count > OBJ_NUMB_MAX_SIZE) {
            det_count = OBJ_NUMB_MAX_SIZE;
        }
    }

    std::vector<uint8_t> meta;
    meta.reserve(4 + 5 * sizeof(uint32_t) + det_count * (sizeof(uint32_t) + 5 * sizeof(float)));
    meta.insert(meta.end(), kProtocolMagic, kProtocolMagic + 4);
    append_u32_le(&meta, width);
    append_u32_le(&meta, height);
    append_u32_le(&meta, frame_index);
    append_u32_le(&meta, det_count);
    append_u32_le(&meta, static_cast<uint32_t>(frame.size()));

    for (uint32_t i = 0; i < det_count; ++i) {
        const object_detect_result &det = results.results[i];
        const uint32_t class_id = det.cls_id < 0 ? 0U : static_cast<uint32_t>(det.cls_id);
        append_u32_le(&meta, class_id);
        append_f32_le(&meta, det.prop);
        append_f32_le(&meta, static_cast<float>(det.box.left));
        append_f32_le(&meta, static_cast<float>(det.box.top));
        append_f32_le(&meta, static_cast<float>(det.box.right));
        append_f32_le(&meta, static_cast<float>(det.box.bottom));
    }

    return write_all(stream_fd, meta.data(), meta.size()) &&
           write_all(stream_fd, frame.data(), frame.size());
}

static int setup_stream_fd()
{
    fflush(stdout);
    int stream_fd = dup(STDOUT_FILENO);
    if (stream_fd < 0) {
        fprintf(stderr, "dup stdout failed: %s\n", strerror(errno));
        return -1;
    }
    if (dup2(STDERR_FILENO, STDOUT_FILENO) < 0) {
        fprintf(stderr, "dup2 stderr to stdout failed: %s\n", strerror(errno));
        close(stream_fd);
        return -1;
    }

    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
    signal(SIGPIPE, SIG_IGN);
    return stream_fd;
}

static bool prepare_roi_rgb(const Options &opts, const image_buffer_t &src,
                            std::vector<uint8_t> *roi_rgb, image_buffer_t *dst,
                            uint32_t *offset_x, uint32_t *offset_y)
{
    if (!opts.roi_enabled) {
        *dst = src;
        *offset_x = 0;
        *offset_y = 0;
        return true;
    }

    if (src.format != IMAGE_FORMAT_RGB888) {
        fprintf(stderr, "--roi currently requires RGB888 inference input; got format=%d\n", src.format);
        return false;
    }
    if (src.virt_addr == NULL || src.width <= 0 || src.height <= 0 || src.width_stride <= 0) {
        fprintf(stderr, "--roi cannot crop an invalid source image\n");
        return false;
    }

    const uint32_t src_width = static_cast<uint32_t>(src.width);
    const uint32_t src_height = static_cast<uint32_t>(src.height);
    if (opts.roi_x >= src_width || opts.roi_y >= src_height) {
        fprintf(stderr, "--roi origin %u,%u is outside source image %ux%u\n",
                opts.roi_x, opts.roi_y, src_width, src_height);
        return false;
    }

    const uint32_t roi_x = opts.roi_x;
    const uint32_t roi_y = opts.roi_y;
    const uint32_t roi_w = std::min(opts.roi_w, src_width - roi_x);
    const uint32_t roi_h = std::min(opts.roi_h, src_height - roi_y);
    if (roi_w < 2 || roi_h < 2) {
        fprintf(stderr, "--roi clipped to an invalid size %ux%u\n", roi_w, roi_h);
        return false;
    }

    roi_rgb->resize(static_cast<size_t>(roi_w) * roi_h * 3);
    const uint8_t *src_ptr = src.virt_addr;
    for (uint32_t row = 0; row < roi_h; ++row) {
        const size_t src_offset = (static_cast<size_t>(roi_y + row) * src.width_stride + roi_x) * 3;
        const size_t dst_offset = static_cast<size_t>(row) * roi_w * 3;
        memcpy(roi_rgb->data() + dst_offset, src_ptr + src_offset, static_cast<size_t>(roi_w) * 3);
    }

    memset(dst, 0, sizeof(*dst));
    dst->width = static_cast<int>(roi_w);
    dst->height = static_cast<int>(roi_h);
    dst->width_stride = static_cast<int>(roi_w);
    dst->height_stride = static_cast<int>(roi_h);
    dst->format = IMAGE_FORMAT_RGB888;
    dst->virt_addr = roi_rgb->data();
    dst->size = static_cast<int>(roi_rgb->size());
    dst->fd = 0;
    *offset_x = roi_x;
    *offset_y = roi_y;
    return true;
}

static int clamp_i32(int value, int low, int high)
{
    return std::max(low, std::min(value, high));
}

static void translate_results_from_roi(object_detect_result_list *results,
                                       uint32_t offset_x, uint32_t offset_y,
                                       uint32_t image_width, uint32_t image_height)
{
    if (offset_x == 0 && offset_y == 0) {
        return;
    }

    const int max_x = static_cast<int>(image_width) - 1;
    const int max_y = static_cast<int>(image_height) - 1;
    for (int i = 0; i < results->count && i < OBJ_NUMB_MAX_SIZE; ++i) {
        image_rect_t *box = &results->results[i].box;
        box->left = clamp_i32(box->left + static_cast<int>(offset_x), 0, max_x);
        box->right = clamp_i32(box->right + static_cast<int>(offset_x), 0, max_x);
        box->top = clamp_i32(box->top + static_cast<int>(offset_y), 0, max_y);
        box->bottom = clamp_i32(box->bottom + static_cast<int>(offset_y), 0, max_y);
    }
}

}  // namespace

int main(int argc, char **argv)
{
    const int stream_fd = setup_stream_fd();
    if (stream_fd < 0) {
        return 1;
    }

    Options opts;
    if (!parse_args(argc, argv, &opts)) {
        close(stream_fd);
        return 2;
    }

    int exit_code = 0;
    bool post_process_ready = false;
    bool camera_started = false;
    CameraContext camera;
    rknn_app_context_t rknn_app_ctx;
    memset(&rknn_app_ctx, 0, sizeof(rknn_app_ctx));

    const size_t frame_size = static_cast<size_t>(opts.width) * opts.height * 3 / 2;
    std::vector<uint8_t> frame;
    frame.reserve(frame_size);
    std::vector<uint8_t> rgb_frame;
    rgb_frame.reserve(static_cast<size_t>(opts.width) * opts.height * 3);
    std::vector<uint8_t> roi_rgb_frame;
    uint32_t captured = 0;
    uint32_t emitted = 0;
    uint32_t consecutive_mjpeg_errors = 0;
    const uint32_t max_consecutive_mjpeg_errors = 60;

    if (init_post_process() != 0) {
        fprintf(stderr, "init_post_process failed\n");
        exit_code = 1;
        goto out;
    }
    post_process_ready = true;

    if (init_yolo11_model(opts.model.c_str(), &rknn_app_ctx) != 0) {
        fprintf(stderr, "init_yolo11_model failed: %s\n", opts.model.c_str());
        exit_code = 1;
        goto out;
    }
    rknn_app_ctx.box_conf_threshold = opts.conf_threshold;
    rknn_app_ctx.nms_threshold = opts.nms_threshold;

    if (!open_camera(opts, &camera)) {
        exit_code = 1;
        goto out;
    }
    if (!start_camera(&camera)) {
        exit_code = 1;
        goto out;
    }
    camera_started = true;

    fprintf(stderr,
            "streaming %s packets to stdout: frames=%u skip=%u payload=%zu conf=%.3f nms=%.3f roi=%s",
            LIVE_APP_NAME, opts.frames, opts.skip, frame_size,
            opts.conf_threshold, opts.nms_threshold, opts.roi_enabled ? "on" : "off");
    if (opts.roi_enabled) {
        fprintf(stderr, ":%u,%u,%u,%u", opts.roi_x, opts.roi_y, opts.roi_w, opts.roi_h);
    }
    fprintf(stderr, "\n");

    while (opts.frames == 0 || emitted < opts.frames) {
        struct v4l2_buffer buf;
        struct v4l2_plane planes[VIDEO_MAX_PLANES];
        if (!dequeue_buffer(&camera, &buf, planes)) {
            exit_code = 1;
            break;
        }

        if (captured < opts.skip) {
            ++captured;
            if (!queue_buffer(&camera, buf.index)) {
                exit_code = 1;
                break;
            }
            continue;
        }
        ++captured;

        image_buffer_t image;
        memset(&image, 0, sizeof(image));
        image.width = opts.width;
        image.height = opts.height;
        image.width_stride = opts.width;
        image.height_stride = opts.height;
        image.fd = 0;

        if (camera.input_format == CAMERA_INPUT_NV12) {
            if (!copy_nv12_frame(camera, buf, planes, &frame)) {
                exit_code = 1;
                queue_buffer(&camera, buf.index);
                break;
            }
            image.format = IMAGE_FORMAT_YUV420SP_NV12;
            image.virt_addr = frame.data();
            image.size = static_cast<int>(frame.size());
        } else if (camera.input_format == CAMERA_INPUT_YUYV) {
            if (!copy_yuyv_frame(camera, buf, &rgb_frame, &frame)) {
                exit_code = 1;
                queue_buffer(&camera, buf.index);
                break;
            }
            image.format = IMAGE_FORMAT_RGB888;
            image.virt_addr = rgb_frame.data();
            image.size = static_cast<int>(rgb_frame.size());
        } else {
            if (!copy_mjpeg_frame(camera, buf, &rgb_frame, &frame, &image)) {
                ++consecutive_mjpeg_errors;
                queue_buffer(&camera, buf.index);
                if (consecutive_mjpeg_errors > max_consecutive_mjpeg_errors) {
                    fprintf(stderr, "too many consecutive MJPG decode failures (%u); exiting\n",
                            consecutive_mjpeg_errors);
                    exit_code = 1;
                    break;
                }
                continue;
            }
        }
        consecutive_mjpeg_errors = 0;

        object_detect_result_list od_results;
        memset(&od_results, 0, sizeof(od_results));
        image_buffer_t infer_image;
        uint32_t roi_offset_x = 0;
        uint32_t roi_offset_y = 0;
        if (!prepare_roi_rgb(opts, image, &roi_rgb_frame, &infer_image, &roi_offset_x, &roi_offset_y)) {
            exit_code = 1;
            queue_buffer(&camera, buf.index);
            break;
        }

        const int infer_ret = inference_yolo11_model(&rknn_app_ctx, &infer_image, &od_results);
        if (infer_ret != 0) {
            fprintf(stderr, "inference_yolo11_model failed: ret=%d frame=%u\n", infer_ret, emitted);
            exit_code = 1;
            queue_buffer(&camera, buf.index);
            break;
        }
        translate_results_from_roi(&od_results, roi_offset_x, roi_offset_y, opts.width, opts.height);

        if (!write_frame_packet(stream_fd, opts.width, opts.height, emitted, od_results, frame)) {
            fprintf(stderr, "write stream failed: %s\n", strerror(errno));
            exit_code = 1;
            queue_buffer(&camera, buf.index);
            break;
        }

        ++emitted;
        if (!queue_buffer(&camera, buf.index)) {
            exit_code = 1;
            break;
        }
    }

out:
    if (camera_started) {
        stop_camera(&camera);
    }
    close_camera(&camera);
    release_yolo11_model(&rknn_app_ctx);
    if (post_process_ready) {
        deinit_post_process();
    }
    close(stream_fd);
    return exit_code;
}
