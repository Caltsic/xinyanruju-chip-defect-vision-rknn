// Copyright (c) 2026.
//
// Live V4L2 NV12 camera stream for RKNN YOLO11.

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

#include <limits>
#include <string>
#include <vector>

#include "yolo11-pose.h"
#include "image_utils.h"

namespace {

static_assert(sizeof(uint32_t) == 4, "protocol requires 32-bit uint32_t");
static_assert(sizeof(float) == 4, "protocol requires 32-bit float");

const char kDefaultModel[] = "model/yolo11n_pose_rk3576_fp.rknn";
const char kDefaultDevice[] = "/dev/video42";
const uint32_t kDefaultWidth = 640;
const uint32_t kDefaultHeight = 360;
const uint32_t kDefaultFps = 5;
const uint32_t kDefaultFrames = 0;
const uint32_t kDefaultSkip = 8;
const uint32_t kDefaultBuffers = 4;
const uint32_t kMaxPayloadSize = std::numeric_limits<uint32_t>::max();
const char kProtocolMagic[] = "RYP1";

struct Options {
    std::string model;
    std::string device;
    uint32_t width;
    uint32_t height;
    uint32_t fps;
    uint32_t frames;
    uint32_t skip;
    uint32_t buffers;

    Options()
        : model(kDefaultModel),
          device(kDefaultDevice),
          width(kDefaultWidth),
          height(kDefaultHeight),
          fps(kDefaultFps),
          frames(kDefaultFrames),
          skip(kDefaultSkip),
          buffers(kDefaultBuffers) {}
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
    uint32_t width;
    uint32_t height;
    uint32_t num_planes;
    size_t y_stride;
    size_t uv_stride;
    std::vector<CameraBuffer> buffers;

    CameraContext()
        : fd(-1), width(0), height(0), num_planes(0), y_stride(0), uv_stride(0) {}
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

static void print_usage(const char *prog)
{
    fprintf(stderr,
            "Usage: %s [--model PATH] [--device NODE] [--width N] [--height N] "
            "[--fps N] [--frames N] [--skip N] [--buffers N]\n"
            "Defaults: --model %s --device %s --width %u --height %u "
            "--fps %u --frames %u --skip %u --buffers %u\n",
            prog, kDefaultModel, kDefaultDevice, kDefaultWidth, kDefaultHeight,
            kDefaultFps, kDefaultFrames, kDefaultSkip, kDefaultBuffers);
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

    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.index = index;
    buf.length = cam->num_planes;
    buf.m.planes = planes;

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
    if ((caps & V4L2_CAP_VIDEO_CAPTURE_MPLANE) == 0) {
        fprintf(stderr, "%s is not a Video Capture Multiplanar device\n", opts.device.c_str());
        return false;
    }
    if ((caps & V4L2_CAP_STREAMING) == 0) {
        fprintf(stderr, "%s does not support streaming I/O\n", opts.device.c_str());
        return false;
    }

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

    struct v4l2_streamparm parm;
    memset(&parm, 0, sizeof(parm));
    parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    parm.parm.capture.timeperframe.numerator = 1;
    parm.parm.capture.timeperframe.denominator = opts.fps;
    if (xioctl(cam->fd, VIDIOC_S_PARM, &parm) < 0) {
        fprintf(stderr, "warning: VIDIOC_S_PARM fps=%u failed: %s\n", opts.fps, strerror(errno));
    }

    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = opts.buffers;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
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

        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        buf.length = cam->num_planes;
        buf.m.planes = planes;

        if (xioctl(cam->fd, VIDIOC_QUERYBUF, &buf) < 0) {
            fprintf(stderr, "VIDIOC_QUERYBUF index=%u failed: %s\n", i, strerror(errno));
            return false;
        }

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
    }

    for (uint32_t i = 0; i < req.count; ++i) {
        if (!queue_buffer(cam, i)) {
            return false;
        }
    }

    fprintf(stderr, "camera %s configured: %ux%u NV12, fps=%u, buffers=%u, planes=%u\n",
            opts.device.c_str(), cam->width, cam->height, opts.fps, req.count, cam->num_planes);
    return true;
}

static bool start_camera(CameraContext *cam)
{
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
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
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
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
        buf->type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        buf->memory = V4L2_MEMORY_MMAP;
        buf->length = cam->num_planes;
        buf->m.planes = planes;

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

    std::vector<uint8_t> header;
    std::vector<uint8_t> meta;
    meta.reserve(det_count * (sizeof(uint32_t) + 5 * sizeof(float) + KEYPOINT_NUM * 3 * sizeof(float)));

    for (uint32_t i = 0; i < det_count; ++i) {
        const object_detect_result &det = results.results[i];
        const uint32_t class_id = det.cls_id < 0 ? 0U : static_cast<uint32_t>(det.cls_id);
        append_u32_le(&meta, class_id);
        append_f32_le(&meta, det.prop);
        append_f32_le(&meta, static_cast<float>(det.box.left));
        append_f32_le(&meta, static_cast<float>(det.box.top));
        append_f32_le(&meta, static_cast<float>(det.box.right));
        append_f32_le(&meta, static_cast<float>(det.box.bottom));
        for (uint32_t j = 0; j < KEYPOINT_NUM; ++j) {
            append_f32_le(&meta, det.keypoints[j][0]);
            append_f32_le(&meta, det.keypoints[j][1]);
            append_f32_le(&meta, det.keypoints[j][2]);
        }
    }

    header.reserve(4 + 8 * sizeof(uint32_t));
    header.insert(header.end(), kProtocolMagic, kProtocolMagic + 4);
    append_u32_le(&header, width);
    append_u32_le(&header, height);
    append_u32_le(&header, frame_index);
    append_u32_le(&header, det_count);
    append_u32_le(&header, KEYPOINT_NUM);
    append_u32_le(&header, 0);
    append_u32_le(&header, static_cast<uint32_t>(meta.size()));
    append_u32_le(&header, static_cast<uint32_t>(frame.size()));

    return write_all(stream_fd, header.data(), header.size()) &&
           write_all(stream_fd, meta.data(), meta.size()) &&
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
    uint32_t captured = 0;
    uint32_t emitted = 0;

    if (init_post_process() != 0) {
        fprintf(stderr, "init_post_process failed\n");
        exit_code = 1;
        goto out;
    }
    post_process_ready = true;

    if (init_yolo11_pose_model(opts.model.c_str(), &rknn_app_ctx) != 0) {
        fprintf(stderr, "init_yolo11_pose_model failed: %s\n", opts.model.c_str());
        exit_code = 1;
        goto out;
    }

    if (!open_camera(opts, &camera)) {
        exit_code = 1;
        goto out;
    }
    if (!start_camera(&camera)) {
        exit_code = 1;
        goto out;
    }
    camera_started = true;

    fprintf(stderr, "streaming RKNN YOLO11 pose packets to stdout: frames=%u skip=%u payload=%zu\n",
            opts.frames, opts.skip, frame_size);

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

        if (!copy_nv12_frame(camera, buf, planes, &frame)) {
            exit_code = 1;
            queue_buffer(&camera, buf.index);
            break;
        }
        if (!queue_buffer(&camera, buf.index)) {
            exit_code = 1;
            break;
        }

        image_buffer_t image;
        memset(&image, 0, sizeof(image));
        image.width = opts.width;
        image.height = opts.height;
        image.width_stride = opts.width;
        image.height_stride = opts.height;
        image.format = IMAGE_FORMAT_YUV420SP_NV12;
        image.virt_addr = frame.data();
        image.size = static_cast<int>(frame.size());
        image.fd = 0;

        object_detect_result_list od_results;
        memset(&od_results, 0, sizeof(od_results));
        const int infer_ret = inference_yolo11_pose_model(&rknn_app_ctx, &image, &od_results);
        if (infer_ret != 0) {
            fprintf(stderr, "inference_yolo11_pose_model failed: ret=%d frame=%u\n", infer_ret, emitted);
            exit_code = 1;
            break;
        }

        if (!write_frame_packet(stream_fd, opts.width, opts.height, emitted, od_results, frame)) {
            fprintf(stderr, "write stream failed: %s\n", strerror(errno));
            exit_code = 1;
            break;
        }

        ++emitted;
    }

out:
    if (camera_started) {
        stop_camera(&camera);
    }
    close_camera(&camera);
    release_yolo11_pose_model(&rknn_app_ctx);
    if (post_process_ready) {
        deinit_post_process();
    }
    close(stream_fd);
    return exit_code;
}
