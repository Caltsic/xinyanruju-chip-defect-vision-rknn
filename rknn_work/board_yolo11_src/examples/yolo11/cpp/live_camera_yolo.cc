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
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <cmath>
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

#ifndef DEFAULT_DEFECT_MODEL_PATH
#define DEFAULT_DEFECT_MODEL_PATH "model/chipcheck_yolov8_detect_split_int8.rknn"
#endif

#ifndef DEFAULT_TWO_STAGE
#ifdef ENABLE_TWO_STAGE
#define DEFAULT_TWO_STAGE 1
#else
#define DEFAULT_TWO_STAGE 0
#endif
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
const char kDefaultDefectModel[] = DEFAULT_DEFECT_MODEL_PATH;
const char kDefaultSegDefectModel[] = "model/chipcheck_yolov8_seg_split_int8.rknn";
const char kDefaultObbChipModel[] = "model/chip_roi_yolov8_obb_split_int8.rknn";
const char kDefaultDevice[] = DEFAULT_DEVICE_PATH;
const char kDefaultFormat[] = DEFAULT_CAMERA_FORMAT;
const uint32_t kDefaultWidth = DEFAULT_CAMERA_WIDTH;
const uint32_t kDefaultHeight = DEFAULT_CAMERA_HEIGHT;
const uint32_t kDefaultFps = DEFAULT_CAMERA_FPS;
const uint32_t kDefaultFrames = 0;
const uint32_t kDefaultSkip = DEFAULT_CAMERA_SKIP;
const uint32_t kDefaultBuffers = 4;
const float kDefaultConfThreshold = BOX_THRESH;
const float kDefaultChipConfThreshold = 0.25f;
const float kDefaultDefectConfThreshold = 0.45f;
const float kDefaultNmsThreshold = NMS_THRESH;
const float kDefaultRoiMargin = 0.08f;
const char kDefaultInputAdjustFile[] = "/tmp/chip_input_adjust.conf";
const uint32_t kMaxPayloadSize = std::numeric_limits<uint32_t>::max();
const char kProtocolMagic[] = "RYL1";
const char kSegSidecarMagic[] = "RYLS";
const uint32_t kSegSidecarVersion = 1;
const uint32_t kSegMaskStatusBboxFallback = 1;
const uint32_t kDetectionContoursFlag = 0x80000000U;

enum CameraInputFormat {
    CAMERA_INPUT_NV12,
    CAMERA_INPUT_YUYV,
    CAMERA_INPUT_MJPEG,
};

struct Options {
    std::string model;
    std::string defect_model;
    bool defect_model_explicit;
    std::string seg_sidecar;
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
    bool two_stage;
    yolo_model_kind_t chip_model_kind;
    yolo_model_kind_t defect_model_kind;
    bool stream_contours;
    bool stream_contours_explicit;
    float conf_threshold;
    float chip_conf_threshold;
    float defect_conf_threshold;
    float nms_threshold;
    float roi_margin;
    float roi_smooth_alpha;
    uint32_t roi_hold;
    uint32_t chip_interval;
    uint32_t defect_interval;
    uint32_t defect_confirm;
    uint32_t defect_hold;
    float defect_smooth_alpha;
    float defect_match_iou;
    float defect_match_center;
    float defect_class_decay;
    bool input_adjust_enabled;
    int input_brightness;
    float input_contrast;
    float input_gamma;
    float input_saturation;
    float input_sharpness;
    std::string input_adjust_file;

    Options()
        : model(kDefaultModel),
          defect_model(kDefaultDefectModel),
          defect_model_explicit(false),
          seg_sidecar(),
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
          two_stage(DEFAULT_TWO_STAGE != 0),
          chip_model_kind(YOLO_MODEL_KIND_DETECT),
          defect_model_kind(YOLO_MODEL_KIND_DETECT),
          stream_contours(false),
          stream_contours_explicit(false),
          conf_threshold(kDefaultConfThreshold),
          chip_conf_threshold(kDefaultChipConfThreshold),
          defect_conf_threshold(kDefaultDefectConfThreshold),
          nms_threshold(kDefaultNmsThreshold),
          roi_margin(kDefaultRoiMargin),
          roi_smooth_alpha(0.35f),
          roi_hold(3),
          chip_interval(3),
          defect_interval(2),
          defect_confirm(3),
          defect_hold(3),
          defect_smooth_alpha(0.35f),
          defect_match_iou(0.10f),
          defect_match_center(0.55f),
          defect_class_decay(0.85f),
          input_adjust_enabled(false),
          input_brightness(-6),
          input_contrast(1.28f),
          input_gamma(0.91f),
          input_saturation(0.30f),
          input_sharpness(0.85f),
          input_adjust_file(kDefaultInputAdjustFile) {}
};

struct InputAdjustParams {
    bool enabled;
    int brightness;
    float contrast;
    float gamma;
    float saturation;
    float sharpness;

    InputAdjustParams()
        : enabled(false),
          brightness(0),
          contrast(1.0f),
          gamma(1.0f),
          saturation(1.0f),
          sharpness(0.0f) {}
};

struct InputAdjustRuntime {
    InputAdjustParams params;
    uint8_t lut[256];
    time_t config_mtime;
    long config_mtime_nsec;
    bool lut_ready;
    std::vector<uint8_t> scratch;

    InputAdjustRuntime() : config_mtime(0), config_mtime_nsec(0), lut_ready(false)
    {
        memset(lut, 0, sizeof(lut));
    }
};

struct TemporalBoxState {
    bool has_box;
    object_detect_result box;
    uint32_t missed;

    TemporalBoxState() : has_box(false), missed(0)
    {
        memset(&box, 0, sizeof(box));
    }
};

struct TemporalObbState {
    bool has_box;
    object_obb_result box;
    uint32_t missed;

    TemporalObbState() : has_box(false), missed(0)
    {
        memset(&box, 0, sizeof(box));
    }
};

struct DefectTrack {
    object_detect_result det;
    std::vector<float> class_scores;
    uint32_t hits;
    uint32_t consecutive_hits;
    uint32_t missed;
    bool confirmed;
    bool matched_this_update;

    DefectTrack()
        : hits(0),
          consecutive_hits(0),
          missed(0),
          confirmed(false),
          matched_this_update(false)
    {
        memset(&det, 0, sizeof(det));
    }
};

struct SegDefectTrack {
    object_detect_result det;
    object_seg_result seg;
    std::vector<float> class_scores;
    uint32_t hits;
    uint32_t consecutive_hits;
    uint32_t missed;
    bool confirmed;
    bool matched_this_update;

    SegDefectTrack()
        : hits(0),
          consecutive_hits(0),
          missed(0),
          confirmed(false),
          matched_this_update(false)
    {
        memset(&det, 0, sizeof(det));
        memset(&seg, 0, sizeof(seg));
    }
};

struct AffineTransform {
    float a00;
    float a01;
    float a02;
    float a10;
    float a11;
    float a12;

    AffineTransform()
        : a00(1.0f), a01(0.0f), a02(0.0f), a10(0.0f), a11(1.0f), a12(0.0f) {}
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
            "[--fps N] [--frames N] [--skip N] [--buffers N] [--roi X,Y,W,H] [--conf F] [--nms F] "
            "[--two-stage] [--chip-model-kind detect|obb] [--defect-model PATH] [--defect-model-kind detect|seg] [--stream-contours|--no-stream-contours] [--seg-sidecar PATH] "
            "[--chip-conf F] [--defect-conf F] [--roi-margin F] "
            "[--roi-smooth-alpha F] [--roi-hold N] [--chip-interval N] [--defect-interval N] "
            "[--defect-confirm N] [--defect-hold N] [--defect-smooth-alpha F] "
            "[--defect-match-iou F] [--defect-match-center F] [--defect-class-decay F] "
            "[--input-adjust|--no-input-adjust] [--input-brightness N] [--input-contrast F] "
            "[--input-gamma F] [--input-saturation F] [--input-sharpness F] "
            "[--input-adjust-file PATH]\n"
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

static bool parse_i32(const char *text, int *value)
{
    if (text == NULL || text[0] == '\0') {
        return false;
    }

    errno = 0;
    char *end = NULL;
    long parsed = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' ||
        parsed < std::numeric_limits<int>::min() ||
        parsed > std::numeric_limits<int>::max()) {
        return false;
    }

    *value = static_cast<int>(parsed);
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

static bool parse_float_value(const char *text, float *value)
{
    if (text == NULL || text[0] == '\0') {
        return false;
    }

    errno = 0;
    char *end = NULL;
    float parsed = strtof(text, &end);
    if (errno != 0 || end == text || *end != '\0' || !std::isfinite(parsed)) {
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

static bool parse_model_kind(const std::string &text, yolo_model_kind_t *kind)
{
    if (text == "detect") {
        *kind = YOLO_MODEL_KIND_DETECT;
        return true;
    }
    if (text == "seg" || text == "segment" || text == "segmentation") {
        *kind = YOLO_MODEL_KIND_SEG;
        return true;
    }
    if (text == "obb" || text == "rotated" || text == "oriented") {
        *kind = YOLO_MODEL_KIND_OBB;
        return true;
    }
    return false;
}

static const char *model_kind_name(yolo_model_kind_t kind)
{
    switch (kind) {
    case YOLO_MODEL_KIND_DETECT:
        return "detect";
    case YOLO_MODEL_KIND_SEG:
        return "seg";
    case YOLO_MODEL_KIND_OBB:
        return "obb";
    }
    return "detect";
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

static bool parse_int_option(int argc, char **argv, int *index, const char *name, int *value)
{
    std::string text;
    if (!take_option_value(argc, argv, index, name, &text)) {
        return false;
    }
    if (!parse_i32(text.c_str(), value)) {
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

static bool parse_alpha_option(int argc, char **argv, int *index, const char *name, float *value)
{
    std::string text;
    if (!take_option_value(argc, argv, index, name, &text)) {
        return false;
    }
    if (!parse_float_value(text.c_str(), value) || !std::isfinite(*value) || *value <= 0.0f || *value > 1.0f) {
        fprintf(stderr, "invalid value for %s: %s; expected 0.0 < value <= 1.0\n",
                name, text.c_str());
        return false;
    }
    return true;
}

static bool parse_float_value_option(int argc, char **argv, int *index, const char *name, float *value)
{
    std::string text;
    if (!take_option_value(argc, argv, index, name, &text)) {
        return false;
    }
    if (!parse_float_value(text.c_str(), value)) {
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
        } else if (arg == "--defect-model" || arg.compare(0, 15, "--defect-model=") == 0) {
            if (!take_option_value(argc, argv, &i, "--defect-model", &opts->defect_model)) {
                return false;
            }
            opts->defect_model_explicit = true;
        } else if (arg == "--defect-model-kind" || arg.compare(0, 20, "--defect-model-kind=") == 0) {
            std::string kind;
            if (!take_option_value(argc, argv, &i, "--defect-model-kind", &kind)) {
                return false;
            }
            if (!parse_model_kind(kind, &opts->defect_model_kind)) {
                fprintf(stderr, "invalid value for --defect-model-kind: %s; expected detect or seg\n",
                        kind.c_str());
                return false;
            }
        } else if (arg == "--chip-model-kind" || arg.compare(0, 18, "--chip-model-kind=") == 0) {
            std::string kind;
            if (!take_option_value(argc, argv, &i, "--chip-model-kind", &kind)) {
                return false;
            }
            if (!parse_model_kind(kind, &opts->chip_model_kind) ||
                opts->chip_model_kind == YOLO_MODEL_KIND_SEG) {
                fprintf(stderr, "invalid value for --chip-model-kind: %s; expected detect or obb\n",
                        kind.c_str());
                return false;
            }
        } else if (arg == "--seg-sidecar" || arg.compare(0, 14, "--seg-sidecar=") == 0) {
            if (!take_option_value(argc, argv, &i, "--seg-sidecar", &opts->seg_sidecar)) {
                return false;
            }
        } else if (arg == "--stream-contours") {
            opts->stream_contours = true;
            opts->stream_contours_explicit = true;
        } else if (arg == "--no-stream-contours") {
            opts->stream_contours = false;
            opts->stream_contours_explicit = true;
        } else if (arg == "--two-stage") {
            opts->two_stage = true;
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
            opts->defect_conf_threshold = opts->conf_threshold;
        } else if (arg == "--chip-conf" || arg.compare(0, 12, "--chip-conf=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--chip-conf", &opts->chip_conf_threshold)) {
                return false;
            }
        } else if (arg == "--defect-conf" || arg.compare(0, 14, "--defect-conf=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--defect-conf", &opts->defect_conf_threshold)) {
                return false;
            }
        } else if (arg == "--roi-margin" || arg.compare(0, 13, "--roi-margin=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--roi-margin", &opts->roi_margin)) {
                return false;
            }
        } else if (arg == "--roi-smooth-alpha" || arg.compare(0, 19, "--roi-smooth-alpha=") == 0) {
            if (!parse_alpha_option(argc, argv, &i, "--roi-smooth-alpha", &opts->roi_smooth_alpha)) {
                return false;
            }
        } else if (arg == "--roi-hold" || arg.compare(0, 11, "--roi-hold=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--roi-hold", &opts->roi_hold)) {
                return false;
            }
        } else if (arg == "--chip-interval" || arg.compare(0, 16, "--chip-interval=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--chip-interval", &opts->chip_interval)) {
                return false;
            }
        } else if (arg == "--defect-interval" || arg.compare(0, 18, "--defect-interval=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--defect-interval", &opts->defect_interval)) {
                return false;
            }
        } else if (arg == "--defect-confirm" || arg.compare(0, 17, "--defect-confirm=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--defect-confirm", &opts->defect_confirm)) {
                return false;
            }
        } else if (arg == "--defect-hold" || arg.compare(0, 14, "--defect-hold=") == 0) {
            if (!parse_numeric_option(argc, argv, &i, "--defect-hold", &opts->defect_hold)) {
                return false;
            }
        } else if (arg == "--defect-smooth-alpha" || arg.compare(0, 22, "--defect-smooth-alpha=") == 0) {
            if (!parse_alpha_option(argc, argv, &i, "--defect-smooth-alpha", &opts->defect_smooth_alpha)) {
                return false;
            }
        } else if (arg == "--defect-match-iou" || arg.compare(0, 19, "--defect-match-iou=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--defect-match-iou", &opts->defect_match_iou)) {
                return false;
            }
        } else if (arg == "--defect-match-center" || arg.compare(0, 22, "--defect-match-center=") == 0) {
            if (!parse_float_option(argc, argv, &i, "--defect-match-center", &opts->defect_match_center)) {
                return false;
            }
        } else if (arg == "--defect-class-decay" || arg.compare(0, 21, "--defect-class-decay=") == 0) {
            if (!parse_alpha_option(argc, argv, &i, "--defect-class-decay", &opts->defect_class_decay)) {
                return false;
            }
        } else if (arg == "--input-adjust") {
            opts->input_adjust_enabled = true;
        } else if (arg == "--no-input-adjust") {
            opts->input_adjust_enabled = false;
        } else if (arg == "--input-brightness" || arg.rfind("--input-brightness=", 0) == 0) {
            if (!parse_int_option(argc, argv, &i, "--input-brightness", &opts->input_brightness)) {
                return false;
            }
        } else if (arg == "--input-contrast" || arg.rfind("--input-contrast=", 0) == 0) {
            if (!parse_float_value_option(argc, argv, &i, "--input-contrast", &opts->input_contrast)) {
                return false;
            }
        } else if (arg == "--input-gamma" || arg.rfind("--input-gamma=", 0) == 0) {
            if (!parse_float_value_option(argc, argv, &i, "--input-gamma", &opts->input_gamma)) {
                return false;
            }
        } else if (arg == "--input-saturation" || arg.rfind("--input-saturation=", 0) == 0) {
            if (!parse_float_value_option(argc, argv, &i, "--input-saturation", &opts->input_saturation)) {
                return false;
            }
        } else if (arg == "--input-sharpness" || arg.rfind("--input-sharpness=", 0) == 0) {
            if (!parse_float_value_option(argc, argv, &i, "--input-sharpness", &opts->input_sharpness)) {
                return false;
            }
        } else if (arg == "--input-adjust-file" || arg.rfind("--input-adjust-file=", 0) == 0) {
            if (!take_option_value(argc, argv, &i, "--input-adjust-file", &opts->input_adjust_file)) {
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
    if (!opts->seg_sidecar.empty() && opts->defect_model_kind != YOLO_MODEL_KIND_SEG) {
        fprintf(stderr, "--seg-sidecar is only valid with --defect-model-kind seg\n");
        return false;
    }
    if (opts->defect_model_kind == YOLO_MODEL_KIND_SEG && !opts->defect_model_explicit) {
        opts->defect_model = kDefaultSegDefectModel;
    }
    if (opts->two_stage && opts->chip_model_kind == YOLO_MODEL_KIND_OBB && opts->model == kDefaultModel) {
        opts->model = kDefaultObbChipModel;
    }
    if (opts->two_stage && opts->defect_model.empty()) {
        fprintf(stderr, "--defect-model must not be empty in --two-stage mode\n");
        return false;
    }
    if ((opts->defect_model_kind == YOLO_MODEL_KIND_SEG || opts->chip_model_kind == YOLO_MODEL_KIND_OBB) &&
        !opts->stream_contours_explicit) {
        opts->stream_contours = true;
    }
    if (opts->device.empty()) {
        fprintf(stderr, "--device must not be empty\n");
        return false;
    }
    if (opts->chip_interval == 0) {
        opts->chip_interval = 1;
    }
    if (opts->defect_interval == 0) {
        opts->defect_interval = 1;
    }
    if (opts->defect_confirm == 0) {
        opts->defect_confirm = 1;
    }
    opts->input_contrast = std::max(0.0f, std::min(opts->input_contrast, 5.0f));
    opts->input_gamma = std::max(0.05f, std::min(opts->input_gamma, 5.0f));
    opts->input_saturation = std::max(0.0f, std::min(opts->input_saturation, 5.0f));
    opts->input_sharpness = std::max(0.0f, std::min(opts->input_sharpness, 3.0f));
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

static InputAdjustParams input_adjust_from_options(const Options &opts)
{
    InputAdjustParams params;
    params.enabled = opts.input_adjust_enabled;
    params.brightness = opts.input_brightness;
    params.contrast = std::max(0.0f, std::min(opts.input_contrast, 5.0f));
    params.gamma = std::max(0.05f, std::min(opts.input_gamma, 5.0f));
    params.saturation = std::max(0.0f, std::min(opts.input_saturation, 5.0f));
    params.sharpness = std::max(0.0f, std::min(opts.input_sharpness, 3.0f));
    return params;
}

static std::string trim_text(const std::string &text)
{
    const size_t start = text.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return std::string();
    }
    const size_t end = text.find_last_not_of(" \t\r\n");
    return text.substr(start, end - start + 1);
}

static void rebuild_input_adjust_lut(InputAdjustRuntime *adjust)
{
    const float contrast = std::max(0.0f, std::min(adjust->params.contrast, 5.0f));
    const float gamma = std::max(0.05f, std::min(adjust->params.gamma, 5.0f));
    const float inv_gamma = 1.0f / gamma;
    for (int value = 0; value < 256; ++value) {
        float adjusted = static_cast<float>(value) * contrast +
                         static_cast<float>(adjust->params.brightness);
        adjusted = std::max(0.0f, std::min(adjusted, 255.0f));
        if (std::fabs(gamma - 1.0f) > 0.001f) {
            adjusted = std::pow(adjusted / 255.0f, inv_gamma) * 255.0f;
        }
        adjust->lut[value] = clamp_u8(static_cast<int>(adjusted + 0.5f));
    }
    adjust->lut_ready = true;
}

static void set_input_adjust_value(InputAdjustParams *params,
                                   const std::string &key,
                                   const std::string &value)
{
    if (key == "enabled") {
        int parsed = 0;
        if (parse_i32(value.c_str(), &parsed)) {
            params->enabled = parsed != 0;
        }
        return;
    }
    if (key == "brightness") {
        int parsed = 0;
        if (parse_i32(value.c_str(), &parsed)) {
            params->brightness = parsed;
        }
        return;
    }

    float parsed = 0.0f;
    if (!parse_float_value(value.c_str(), &parsed)) {
        return;
    }
    if (key == "contrast") {
        params->contrast = std::max(0.0f, std::min(parsed, 5.0f));
    } else if (key == "gamma") {
        params->gamma = std::max(0.05f, std::min(parsed, 5.0f));
    } else if (key == "saturation") {
        params->saturation = std::max(0.0f, std::min(parsed, 5.0f));
    } else if (key == "sharpness") {
        params->sharpness = std::max(0.0f, std::min(parsed, 3.0f));
    }
}

static bool read_input_adjust_file(const std::string &path, InputAdjustParams *params)
{
    FILE *file = fopen(path.c_str(), "r");
    if (file == NULL) {
        return false;
    }

    char line[256];
    while (fgets(line, sizeof(line), file) != NULL) {
        std::string text = trim_text(line);
        if (text.empty() || text[0] == '#') {
            continue;
        }
        const size_t equals = text.find('=');
        if (equals == std::string::npos) {
            continue;
        }
        const std::string key = trim_text(text.substr(0, equals));
        const std::string value = trim_text(text.substr(equals + 1));
        set_input_adjust_value(params, key, value);
    }
    fclose(file);
    return true;
}

static void refresh_input_adjust_runtime(const Options &opts, InputAdjustRuntime *adjust)
{
    if (!adjust->lut_ready) {
        adjust->params = input_adjust_from_options(opts);
        rebuild_input_adjust_lut(adjust);
    }

    if (opts.input_adjust_file.empty()) {
        return;
    }

    struct stat st;
    if (stat(opts.input_adjust_file.c_str(), &st) != 0) {
        return;
    }
    const long mtime_nsec = st.st_mtim.tv_nsec;
    if (adjust->config_mtime == st.st_mtime && adjust->config_mtime_nsec == mtime_nsec) {
        return;
    }

    InputAdjustParams params = adjust->params;
    if (read_input_adjust_file(opts.input_adjust_file, &params)) {
        adjust->params = params;
        adjust->config_mtime = st.st_mtime;
        adjust->config_mtime_nsec = mtime_nsec;
        rebuild_input_adjust_lut(adjust);
    }
}

static void apply_input_adjustment(uint8_t *rgb,
                                   uint32_t width,
                                   uint32_t height,
                                   InputAdjustRuntime *adjust)
{
    if (rgb == NULL || width == 0 || height == 0 || !adjust->params.enabled) {
        return;
    }

    const size_t pixel_count = static_cast<size_t>(width) * height;
    const int sat_q8 = static_cast<int>(std::max(0.0f, std::min(adjust->params.saturation, 5.0f)) * 256.0f + 0.5f);
    const int sharp_q8 = static_cast<int>(std::max(0.0f, std::min(adjust->params.sharpness, 3.0f)) * 256.0f + 0.5f);
    const bool sharpen = sharp_q8 > 0 && width >= 3 && height >= 3;
    if (sharpen) {
        adjust->scratch.resize(pixel_count);
    }
    for (size_t index = 0; index < pixel_count; ++index) {
        uint8_t *p = rgb + index * 3;
        int r = adjust->lut[p[0]];
        int g = adjust->lut[p[1]];
        int b = adjust->lut[p[2]];
        if (sat_q8 != 256) {
            const int gray = (77 * r + 150 * g + 29 * b + 128) >> 8;
            r = gray + (((r - gray) * sat_q8) >> 8);
            g = gray + (((g - gray) * sat_q8) >> 8);
            b = gray + (((b - gray) * sat_q8) >> 8);
        }
        p[0] = clamp_u8(r);
        p[1] = clamp_u8(g);
        p[2] = clamp_u8(b);
        if (sharpen) {
            adjust->scratch[index] = clamp_u8((77 * p[0] + 150 * p[1] + 29 * p[2] + 128) >> 8);
        }
    }

    if (!sharpen) {
        return;
    }

    const uint8_t *luma = adjust->scratch.data();
    for (uint32_t row = 1; row + 1 < height; ++row) {
        for (uint32_t col = 1; col + 1 < width; ++col) {
            const size_t pixel_offset = static_cast<size_t>(row) * width + col;
            const int center = luma[pixel_offset];
            const int blur = (center * 4 +
                              luma[pixel_offset - 1] +
                              luma[pixel_offset + 1] +
                              luma[pixel_offset - width] +
                              luma[pixel_offset + width] + 4) >> 3;
            const int boost = ((center - blur) * sharp_q8) >> 8;
            const size_t offset = pixel_offset * 3;
            for (int channel = 0; channel < 3; ++channel) {
                rgb[offset + channel] = clamp_u8(static_cast<int>(rgb[offset + channel]) + boost);
            }
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
    (void)nv12_out;
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

static bool write_seg_sidecar_packet(int fd, uint32_t width, uint32_t height, uint32_t frame_index,
                                     const object_detect_result_list &bbox_fallback)
{
    uint32_t det_count = 0;
    if (bbox_fallback.count > 0) {
        det_count = static_cast<uint32_t>(bbox_fallback.count);
        if (det_count > OBJ_NUMB_MAX_SIZE) {
            det_count = OBJ_NUMB_MAX_SIZE;
        }
    }

    std::vector<uint8_t> payload;
    payload.reserve(4 + 7 * sizeof(uint32_t) + det_count * (8 * sizeof(uint32_t) + 5 * sizeof(float)));
    payload.insert(payload.end(), kSegSidecarMagic, kSegSidecarMagic + 4);
    append_u32_le(&payload, kSegSidecarVersion);
    append_u32_le(&payload, width);
    append_u32_le(&payload, height);
    append_u32_le(&payload, frame_index);
    append_u32_le(&payload, kSegMaskStatusBboxFallback);
    append_u32_le(&payload, det_count);
    append_u32_le(&payload, 0);

    for (uint32_t i = 0; i < det_count; ++i) {
        const object_detect_result &det = bbox_fallback.results[i];
        const uint32_t class_id = det.cls_id < 0 ? 0U : static_cast<uint32_t>(det.cls_id);
        append_u32_le(&payload, class_id);
        append_f32_le(&payload, det.prop);
        append_f32_le(&payload, static_cast<float>(det.box.left));
        append_f32_le(&payload, static_cast<float>(det.box.top));
        append_f32_le(&payload, static_cast<float>(det.box.right));
        append_f32_le(&payload, static_cast<float>(det.box.bottom));
        append_u32_le(&payload, 0);
        append_u32_le(&payload, 0);
        append_u32_le(&payload, 0);
    }

    return write_all(fd, payload.data(), payload.size());
}

static bool append_seg_contour_points(std::vector<uint8_t> *block,
                                      const object_seg_result *seg)
{
    if (seg == NULL || seg->contour_count <= 0) {
        append_u32_le(block, 0);
        return false;
    }

    const object_seg_contour &contour = seg->contours[0];
    uint32_t point_count = 0;
    if (contour.count > 0) {
        point_count = static_cast<uint32_t>(std::min(contour.count, 64));
    }
    append_u32_le(block, point_count);
    for (uint32_t i = 0; i < point_count; ++i) {
        append_f32_le(block, static_cast<float>(contour.points[i].x));
        append_f32_le(block, static_cast<float>(contour.points[i].y));
    }
    return point_count >= 3;
}

static bool append_obb_contour_points(std::vector<uint8_t> *block,
                                      const object_obb_result *obb)
{
    if (obb == NULL) {
        append_u32_le(block, 0);
        return false;
    }
    append_u32_le(block, 4);
    for (int i = 0; i < 4; ++i) {
        append_f32_le(block, obb->points[i].x);
        append_f32_le(block, obb->points[i].y);
    }
    return true;
}

static bool write_frame_packet_with_seg_contours(int stream_fd, uint32_t width, uint32_t height, uint32_t frame_index,
                                                 const object_detect_result_list &results,
                                                 const object_seg_result_list &seg_results,
                                                 const std::vector<uint8_t> &frame)
{
    uint32_t det_count = 0;
    if (results.count > 0) {
        det_count = static_cast<uint32_t>(results.count);
        if (det_count > OBJ_NUMB_MAX_SIZE) {
            det_count = OBJ_NUMB_MAX_SIZE;
        }
    }

    std::vector<uint8_t> contour_block;
    contour_block.reserve(det_count * (sizeof(uint32_t) + 16 * 2 * sizeof(float)));
    bool has_contours = false;
    for (uint32_t i = 0; i < det_count; ++i) {
        const object_seg_result *seg = NULL;
        if (i > 0 && static_cast<int>(i - 1) < seg_results.count) {
            seg = &seg_results.results[i - 1];
        }
        has_contours = append_seg_contour_points(&contour_block, seg) || has_contours;
    }

    if (!has_contours) {
        return write_frame_packet(stream_fd, width, height, frame_index, results, frame);
    }

    std::vector<uint8_t> meta;
    meta.reserve(4 + 5 * sizeof(uint32_t) + det_count * (sizeof(uint32_t) + 5 * sizeof(float)) +
                 sizeof(uint32_t) + contour_block.size());
    meta.insert(meta.end(), kProtocolMagic, kProtocolMagic + 4);
    append_u32_le(&meta, width);
    append_u32_le(&meta, height);
    append_u32_le(&meta, frame_index);
    append_u32_le(&meta, det_count | kDetectionContoursFlag);
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

    append_u32_le(&meta, static_cast<uint32_t>(contour_block.size()));
    meta.insert(meta.end(), contour_block.begin(), contour_block.end());

    return write_all(stream_fd, meta.data(), meta.size()) &&
           write_all(stream_fd, frame.data(), frame.size());
}

static bool write_frame_packet_with_mixed_contours(int stream_fd, uint32_t width, uint32_t height, uint32_t frame_index,
                                                   const object_detect_result_list &results,
                                                   const object_seg_result_list *seg_results,
                                                   const object_obb_result *chip_obb,
                                                   const std::vector<uint8_t> &frame)
{
    uint32_t det_count = 0;
    if (results.count > 0) {
        det_count = static_cast<uint32_t>(results.count);
        if (det_count > OBJ_NUMB_MAX_SIZE) {
            det_count = OBJ_NUMB_MAX_SIZE;
        }
    }

    std::vector<uint8_t> contour_block;
    contour_block.reserve(det_count * (sizeof(uint32_t) + 16 * 2 * sizeof(float)));
    bool has_contours = false;
    for (uint32_t i = 0; i < det_count; ++i) {
        if (i == 0 && chip_obb != NULL && results.results[i].cls_id == 0) {
            has_contours = append_obb_contour_points(&contour_block, chip_obb) || has_contours;
            continue;
        }
        const object_seg_result *seg = NULL;
        if (seg_results != NULL && i > 0 && static_cast<int>(i - 1) < seg_results->count) {
            seg = &seg_results->results[i - 1];
        }
        has_contours = append_seg_contour_points(&contour_block, seg) || has_contours;
    }

    if (!has_contours) {
        return write_frame_packet(stream_fd, width, height, frame_index, results, frame);
    }

    std::vector<uint8_t> meta;
    meta.reserve(4 + 5 * sizeof(uint32_t) + det_count * (sizeof(uint32_t) + 5 * sizeof(float)) +
                 sizeof(uint32_t) + contour_block.size());
    meta.insert(meta.end(), kProtocolMagic, kProtocolMagic + 4);
    append_u32_le(&meta, width);
    append_u32_le(&meta, height);
    append_u32_le(&meta, frame_index);
    append_u32_le(&meta, det_count | kDetectionContoursFlag);
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

    append_u32_le(&meta, static_cast<uint32_t>(contour_block.size()));
    meta.insert(meta.end(), contour_block.begin(), contour_block.end());

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

static int clamp_i32(int value, int low, int high);

static bool crop_rgb_rect(const image_buffer_t &src, const image_rect_t &box, float margin,
                          std::vector<uint8_t> *roi_rgb, image_buffer_t *dst,
                          uint32_t *offset_x, uint32_t *offset_y)
{
    if (src.format != IMAGE_FORMAT_RGB888 || src.virt_addr == NULL || src.width <= 0 ||
        src.height <= 0 || src.width_stride <= 0) {
        fprintf(stderr, "two-stage crop requires a valid RGB888 source image\n");
        return false;
    }

    const int src_width = src.width;
    const int src_height = src.height;
    const int box_w = std::max(1, box.right - box.left);
    const int box_h = std::max(1, box.bottom - box.top);
    const int margin_x = static_cast<int>(box_w * margin + 0.5f);
    const int margin_y = static_cast<int>(box_h * margin + 0.5f);
    const int left = clamp_i32(box.left - margin_x, 0, src_width - 1);
    const int top = clamp_i32(box.top - margin_y, 0, src_height - 1);
    const int right = clamp_i32(box.right + margin_x, left + 2, src_width);
    const int bottom = clamp_i32(box.bottom + margin_y, top + 2, src_height);
    const uint32_t roi_w = static_cast<uint32_t>(right - left);
    const uint32_t roi_h = static_cast<uint32_t>(bottom - top);

    roi_rgb->resize(static_cast<size_t>(roi_w) * roi_h * 3);
    const uint8_t *src_ptr = src.virt_addr;
    for (uint32_t row = 0; row < roi_h; ++row) {
        const size_t src_offset = (static_cast<size_t>(top) + row) * src.width_stride * 3 +
                                  static_cast<size_t>(left) * 3;
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
    *offset_x = static_cast<uint32_t>(left);
    *offset_y = static_cast<uint32_t>(top);
    return true;
}

static float point_distance(const object_obb_point &a, const object_obb_point &b)
{
    const float dx = a.x - b.x;
    const float dy = a.y - b.y;
    return sqrtf(dx * dx + dy * dy);
}

static uint8_t sample_rgb_bilinear(const image_buffer_t &src, float x, float y, int channel)
{
    const int max_x = src.width - 1;
    const int max_y = src.height - 1;
    x = std::max(0.0f, std::min(x, (float)max_x));
    y = std::max(0.0f, std::min(y, (float)max_y));
    const int x0 = (int)floorf(x);
    const int y0 = (int)floorf(y);
    const int x1 = std::min(x0 + 1, max_x);
    const int y1 = std::min(y0 + 1, max_y);
    const float dx = x - (float)x0;
    const float dy = y - (float)y0;
    const uint8_t *base = src.virt_addr;
    const float p00 = base[((size_t)y0 * src.width_stride + x0) * 3 + channel];
    const float p10 = base[((size_t)y0 * src.width_stride + x1) * 3 + channel];
    const float p01 = base[((size_t)y1 * src.width_stride + x0) * 3 + channel];
    const float p11 = base[((size_t)y1 * src.width_stride + x1) * 3 + channel];
    const float top = p00 * (1.0f - dx) + p10 * dx;
    const float bottom = p01 * (1.0f - dx) + p11 * dx;
    return (uint8_t)std::max(0.0f, std::min(255.0f, top * (1.0f - dy) + bottom * dy + 0.5f));
}

static bool crop_rgb_obb(const image_buffer_t &src, const object_obb_result &obb, float margin,
                         std::vector<uint8_t> *roi_rgb, image_buffer_t *dst,
                         AffineTransform *crop_to_src)
{
    if (src.format != IMAGE_FORMAT_RGB888 || src.virt_addr == NULL || src.width <= 0 ||
        src.height <= 0 || src.width_stride <= 0) {
        fprintf(stderr, "two-stage OBB crop requires a valid RGB888 source image\n");
        return false;
    }

    const float base_w = std::max(2.0f, point_distance(obb.points[0], obb.points[1]));
    const float base_h = std::max(2.0f, point_distance(obb.points[1], obb.points[2]));
    const float margin_scale = 1.0f + 2.0f * std::max(0.0f, margin);
    const int roi_w = std::max(2, (int)ceilf(base_w * margin_scale));
    const int roi_h = std::max(2, (int)ceilf(base_h * margin_scale));
    const float angle = obb.angle;
    const float cos_a = cosf(angle);
    const float sin_a = sinf(angle);
    const float cx = obb.cx;
    const float cy = obb.cy;
    const float half_w = (float)roi_w * 0.5f;
    const float half_h = (float)roi_h * 0.5f;

    roi_rgb->assign((size_t)roi_w * roi_h * 3, 114);
    for (int y = 0; y < roi_h; ++y) {
        for (int x = 0; x < roi_w; ++x) {
            const float local_x = ((float)x + 0.5f) - half_w;
            const float local_y = ((float)y + 0.5f) - half_h;
            const float src_x = cx + local_x * cos_a - local_y * sin_a;
            const float src_y = cy + local_x * sin_a + local_y * cos_a;
            const size_t dst_offset = ((size_t)y * roi_w + x) * 3;
            for (int c = 0; c < 3; ++c) {
                (*roi_rgb)[dst_offset + c] = sample_rgb_bilinear(src, src_x, src_y, c);
            }
        }
    }

    memset(dst, 0, sizeof(*dst));
    dst->width = roi_w;
    dst->height = roi_h;
    dst->width_stride = roi_w;
    dst->height_stride = roi_h;
    dst->format = IMAGE_FORMAT_RGB888;
    dst->virt_addr = roi_rgb->data();
    dst->size = static_cast<int>(roi_rgb->size());
    dst->fd = 0;

    crop_to_src->a00 = cos_a;
    crop_to_src->a01 = -sin_a;
    crop_to_src->a02 = cx - half_w * cos_a + half_h * sin_a;
    crop_to_src->a10 = sin_a;
    crop_to_src->a11 = cos_a;
    crop_to_src->a12 = cy - half_w * sin_a - half_h * cos_a;
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

static void translate_seg_results_from_roi(object_seg_result_list *results,
                                           uint32_t offset_x, uint32_t offset_y,
                                           uint32_t image_width, uint32_t image_height)
{
    if (results == NULL) {
        return;
    }

    object_detect_result_list bbox_results;
    memset(&bbox_results, 0, sizeof(bbox_results));
    bbox_results.count = std::min(results->count, OBJ_NUMB_MAX_SIZE);
    for (int i = 0; i < bbox_results.count; ++i) {
        bbox_results.results[i] = results->results[i].det;
    }
    translate_results_from_roi(&bbox_results, offset_x, offset_y, image_width, image_height);
    for (int i = 0; i < bbox_results.count; ++i) {
        results->results[i].det = bbox_results.results[i];
    }

    const int max_x = static_cast<int>(image_width) - 1;
    const int max_y = static_cast<int>(image_height) - 1;
    for (int i = 0; i < results->count && i < OBJ_NUMB_MAX_SIZE; ++i) {
        object_seg_result *seg = &results->results[i];
        for (int c = 0; c < seg->contour_count && c < 4; ++c) {
            object_seg_contour *contour = &seg->contours[c];
            for (int p = 0; p < contour->count && p < 64; ++p) {
                contour->points[p].x = clamp_i32(contour->points[p].x + static_cast<int>(offset_x), 0, max_x);
                contour->points[p].y = clamp_i32(contour->points[p].y + static_cast<int>(offset_y), 0, max_y);
            }
        }
    }
}

static object_obb_point map_affine_point(const AffineTransform &transform, float x, float y)
{
    object_obb_point point;
    point.x = transform.a00 * x + transform.a01 * y + transform.a02;
    point.y = transform.a10 * x + transform.a11 * y + transform.a12;
    return point;
}

static image_rect_t aabb_from_points_clamped(const object_obb_point *points, int count,
                                             uint32_t image_width, uint32_t image_height)
{
    float min_x = points[0].x;
    float max_x = points[0].x;
    float min_y = points[0].y;
    float max_y = points[0].y;
    for (int i = 1; i < count; ++i) {
        min_x = std::min(min_x, points[i].x);
        max_x = std::max(max_x, points[i].x);
        min_y = std::min(min_y, points[i].y);
        max_y = std::max(max_y, points[i].y);
    }
    const int max_x_i = static_cast<int>(image_width) - 1;
    const int max_y_i = static_cast<int>(image_height) - 1;
    image_rect_t box;
    box.left = clamp_i32((int)floorf(min_x), 0, max_x_i);
    box.top = clamp_i32((int)floorf(min_y), 0, max_y_i);
    box.right = clamp_i32((int)ceilf(max_x), 0, max_x_i);
    box.bottom = clamp_i32((int)ceilf(max_y), 0, max_y_i);
    if (box.right <= box.left) {
        box.right = clamp_i32(box.left + 1, 0, max_x_i);
    }
    if (box.bottom <= box.top) {
        box.bottom = clamp_i32(box.top + 1, 0, max_y_i);
    }
    return box;
}

static void map_results_from_crop(object_detect_result_list *results,
                                  const AffineTransform &transform,
                                  uint32_t image_width, uint32_t image_height)
{
    if (results == NULL) {
        return;
    }
    for (int i = 0; i < results->count && i < OBJ_NUMB_MAX_SIZE; ++i) {
        image_rect_t *box = &results->results[i].box;
        object_obb_point points[4];
        points[0] = map_affine_point(transform, (float)box->left, (float)box->top);
        points[1] = map_affine_point(transform, (float)box->right, (float)box->top);
        points[2] = map_affine_point(transform, (float)box->right, (float)box->bottom);
        points[3] = map_affine_point(transform, (float)box->left, (float)box->bottom);
        *box = aabb_from_points_clamped(points, 4, image_width, image_height);
    }
}

static void map_seg_results_from_crop(object_seg_result_list *results,
                                      const AffineTransform &transform,
                                      uint32_t image_width, uint32_t image_height)
{
    if (results == NULL) {
        return;
    }
    object_detect_result_list bbox_results;
    memset(&bbox_results, 0, sizeof(bbox_results));
    bbox_results.count = std::min(results->count, OBJ_NUMB_MAX_SIZE);
    for (int i = 0; i < bbox_results.count; ++i) {
        bbox_results.results[i] = results->results[i].det;
    }
    map_results_from_crop(&bbox_results, transform, image_width, image_height);
    for (int i = 0; i < bbox_results.count; ++i) {
        results->results[i].det = bbox_results.results[i];
    }

    const int max_x = static_cast<int>(image_width) - 1;
    const int max_y = static_cast<int>(image_height) - 1;
    for (int i = 0; i < results->count && i < OBJ_NUMB_MAX_SIZE; ++i) {
        object_seg_result *seg = &results->results[i];
        for (int c = 0; c < seg->contour_count && c < 4; ++c) {
            object_seg_contour *contour = &seg->contours[c];
            for (int p = 0; p < contour->count && p < 64; ++p) {
                const object_obb_point mapped = map_affine_point(
                    transform,
                    (float)contour->points[p].x,
                    (float)contour->points[p].y);
                contour->points[p].x = clamp_i32((int)lroundf(mapped.x), 0, max_x);
                contour->points[p].y = clamp_i32((int)lroundf(mapped.y), 0, max_y);
            }
        }
    }
}

static bool select_primary_chip(const object_detect_result_list &chip_results,
                                object_detect_result *selected)
{
    float best_score = -1.0f;
    int best_index = -1;
    for (int i = 0; i < chip_results.count && i < OBJ_NUMB_MAX_SIZE; ++i) {
        const object_detect_result &det = chip_results.results[i];
        const int w = det.box.right - det.box.left;
        const int h = det.box.bottom - det.box.top;
        if (w <= 1 || h <= 1) {
            continue;
        }
        const float area = static_cast<float>(w) * static_cast<float>(h);
        const float score = area * std::max(0.01f, det.prop);
        if (score > best_score) {
            best_score = score;
            best_index = i;
        }
    }
    if (best_index < 0) {
        return false;
    }
    *selected = chip_results.results[best_index];
    return true;
}

static object_detect_result obb_to_detection(const object_obb_result &obb)
{
    object_detect_result det;
    memset(&det, 0, sizeof(det));
    det.box = obb.box;
    det.prop = obb.prop;
    det.cls_id = obb.cls_id;
    return det;
}

static bool select_primary_chip_obb(const object_obb_result_list &chip_results,
                                    object_obb_result *selected)
{
    float best_score = -1.0f;
    int best_index = -1;
    for (int i = 0; i < chip_results.count && i < OBJ_NUMB_MAX_SIZE; ++i) {
        const object_obb_result &det = chip_results.results[i];
        const float area = std::max(1.0f, det.width) * std::max(1.0f, det.height);
        const float score = area * std::max(0.01f, det.prop);
        if (score > best_score) {
            best_score = score;
            best_index = i;
        }
    }
    if (best_index < 0) {
        return false;
    }
    *selected = chip_results.results[best_index];
    return true;
}

static float smooth_float_value(float previous, float current, float alpha)
{
    return previous * (1.0f - alpha) + current * alpha;
}

static float smooth_angle_value(float previous, float current, float alpha)
{
    const float pi = 3.14159265358979323846f;
    float delta = current - previous;
    while (delta > pi) {
        delta -= 2.0f * pi;
    }
    while (delta < -pi) {
        delta += 2.0f * pi;
    }
    return previous + delta * alpha;
}

static void refresh_obb_geometry(object_obb_result *obb, uint32_t image_width, uint32_t image_height)
{
    const float half_w = std::max(1.0f, obb->width) * 0.5f;
    const float half_h = std::max(1.0f, obb->height) * 0.5f;
    const float cos_a = cosf(obb->angle);
    const float sin_a = sinf(obb->angle);
    const float corners[4][2] = {
        {-half_w, -half_h},
        {half_w, -half_h},
        {half_w, half_h},
        {-half_w, half_h},
    };
    for (int i = 0; i < 4; ++i) {
        const float x = corners[i][0];
        const float y = corners[i][1];
        obb->points[i].x = obb->cx + x * cos_a - y * sin_a;
        obb->points[i].y = obb->cy + x * sin_a + y * cos_a;
    }
    obb->box = aabb_from_points_clamped(obb->points, 4, image_width, image_height);
}

static void sanitize_obb(object_obb_result *obb, uint32_t image_width, uint32_t image_height)
{
    obb->width = std::max(2.0f, obb->width);
    obb->height = std::max(2.0f, obb->height);
    obb->cx = std::max(0.0f, std::min(obb->cx, (float)image_width - 1.0f));
    obb->cy = std::max(0.0f, std::min(obb->cy, (float)image_height - 1.0f));
    refresh_obb_geometry(obb, image_width, image_height);
}

static object_obb_result smooth_chip_obb_detection(TemporalObbState *state,
                                                   const object_obb_result &current,
                                                   float alpha,
                                                   uint32_t image_width,
                                                   uint32_t image_height)
{
    const float clamped_alpha = std::max(0.01f, std::min(alpha, 1.0f));
    if (!state->has_box) {
        state->box = current;
        state->has_box = true;
        state->missed = 0;
        sanitize_obb(&state->box, image_width, image_height);
        return state->box;
    }

    object_obb_result smoothed = current;
    smoothed.cx = smooth_float_value(state->box.cx, current.cx, clamped_alpha);
    smoothed.cy = smooth_float_value(state->box.cy, current.cy, clamped_alpha);
    smoothed.width = smooth_float_value(state->box.width, current.width, clamped_alpha);
    smoothed.height = smooth_float_value(state->box.height, current.height, clamped_alpha);
    smoothed.angle = smooth_angle_value(state->box.angle, current.angle, clamped_alpha);
    smoothed.prop = smooth_float_value(state->box.prop, current.prop, clamped_alpha);
    sanitize_obb(&smoothed, image_width, image_height);
    state->box = smoothed;
    state->missed = 0;
    return state->box;
}

static bool hold_chip_obb_detection(TemporalObbState *state,
                                    uint32_t max_hold,
                                    object_obb_result *held)
{
    if (!state->has_box || state->missed >= max_hold) {
        return false;
    }
    ++state->missed;
    *held = state->box;
    held->prop *= 0.90f;
    return true;
}

static bool reuse_chip_obb_detection(const TemporalObbState &state,
                                     object_obb_result *held)
{
    if (!state.has_box) {
        return false;
    }
    *held = state.box;
    return true;
}

static int smooth_coord(int previous, int current, float alpha)
{
    const float value = static_cast<float>(previous) * (1.0f - alpha) +
                        static_cast<float>(current) * alpha;
    return static_cast<int>(std::lround(value));
}

static void sanitize_box(image_rect_t *box, uint32_t image_width, uint32_t image_height)
{
    const int max_x = static_cast<int>(image_width) - 1;
    const int max_y = static_cast<int>(image_height) - 1;
    box->left = clamp_i32(box->left, 0, max_x);
    box->right = clamp_i32(box->right, 0, max_x);
    box->top = clamp_i32(box->top, 0, max_y);
    box->bottom = clamp_i32(box->bottom, 0, max_y);
    if (box->right <= box->left) {
        box->left = clamp_i32(box->left, 0, std::max(0, max_x - 2));
        box->right = clamp_i32(box->left + 2, 0, max_x);
    }
    if (box->bottom <= box->top) {
        box->top = clamp_i32(box->top, 0, std::max(0, max_y - 2));
        box->bottom = clamp_i32(box->top + 2, 0, max_y);
    }
}

static object_detect_result smooth_chip_detection(TemporalBoxState *state,
                                                  const object_detect_result &current,
                                                  float alpha,
                                                  uint32_t image_width,
                                                  uint32_t image_height)
{
    const float clamped_alpha = std::max(0.01f, std::min(alpha, 1.0f));
    if (!state->has_box) {
        state->box = current;
        state->has_box = true;
        state->missed = 0;
        sanitize_box(&state->box.box, image_width, image_height);
        return state->box;
    }

    object_detect_result smoothed = current;
    smoothed.box.left = smooth_coord(state->box.box.left, current.box.left, clamped_alpha);
    smoothed.box.top = smooth_coord(state->box.box.top, current.box.top, clamped_alpha);
    smoothed.box.right = smooth_coord(state->box.box.right, current.box.right, clamped_alpha);
    smoothed.box.bottom = smooth_coord(state->box.box.bottom, current.box.bottom, clamped_alpha);
    smoothed.prop = state->box.prop * (1.0f - clamped_alpha) + current.prop * clamped_alpha;
    sanitize_box(&smoothed.box, image_width, image_height);
    state->box = smoothed;
    state->missed = 0;
    return state->box;
}

static bool hold_chip_detection(TemporalBoxState *state,
                                uint32_t max_hold,
                                object_detect_result *held)
{
    if (!state->has_box || state->missed >= max_hold) {
        return false;
    }
    ++state->missed;
    *held = state->box;
    held->prop *= 0.90f;
    return true;
}

static bool reuse_chip_detection(const TemporalBoxState &state,
                                 object_detect_result *held)
{
    if (!state.has_box) {
        return false;
    }
    *held = state.box;
    return true;
}

static float rect_iou(const image_rect_t &a, const image_rect_t &b)
{
    const int left = std::max(a.left, b.left);
    const int top = std::max(a.top, b.top);
    const int right = std::min(a.right, b.right);
    const int bottom = std::min(a.bottom, b.bottom);
    const int inter_w = std::max(0, right - left);
    const int inter_h = std::max(0, bottom - top);
    const float inter = static_cast<float>(inter_w) * static_cast<float>(inter_h);
    if (inter <= 0.0f) {
        return 0.0f;
    }

    const float area_a = static_cast<float>(std::max(0, a.right - a.left)) *
                         static_cast<float>(std::max(0, a.bottom - a.top));
    const float area_b = static_cast<float>(std::max(0, b.right - b.left)) *
                         static_cast<float>(std::max(0, b.bottom - b.top));
    const float uni = area_a + area_b - inter;
    return uni > 0.0f ? inter / uni : 0.0f;
}

static float rect_center_distance_ratio(const image_rect_t &a, const image_rect_t &b)
{
    const float ax = (static_cast<float>(a.left) + static_cast<float>(a.right)) * 0.5f;
    const float ay = (static_cast<float>(a.top) + static_cast<float>(a.bottom)) * 0.5f;
    const float bx = (static_cast<float>(b.left) + static_cast<float>(b.right)) * 0.5f;
    const float by = (static_cast<float>(b.top) + static_cast<float>(b.bottom)) * 0.5f;
    const float dx = ax - bx;
    const float dy = ay - by;
    const float distance = std::sqrt(dx * dx + dy * dy);
    const float scale = std::max(1.0f,
                                 static_cast<float>(std::max(std::max(a.right - a.left, a.bottom - a.top),
                                                             std::max(b.right - b.left, b.bottom - b.top))));
    return distance / scale;
}

static int dominant_class(const std::vector<float> &scores, int fallback)
{
    float best = -1.0f;
    int best_class = fallback;
    for (size_t i = 0; i < scores.size(); ++i) {
        if (scores[i] > best) {
            best = scores[i];
            best_class = static_cast<int>(i);
        }
    }
    return best_class;
}

static int stable_dominant_class(const std::vector<float> &scores, int current, int fallback)
{
    const int best_class = dominant_class(scores, fallback);
    if (current < 0 || current >= static_cast<int>(scores.size()) || best_class == current) {
        return best_class;
    }

    const float current_score = scores[static_cast<size_t>(current)];
    const float best_score = best_class >= 0 && best_class < static_cast<int>(scores.size())
                                 ? scores[static_cast<size_t>(best_class)]
                                 : 0.0f;
    if (current_score <= 0.0f) {
        return best_class;
    }

    const float switch_threshold = current_score * 1.25f + 0.05f;
    return best_score > switch_threshold ? best_class : current;
}

class DefectTemporalFilter {
public:
    DefectTemporalFilter() : class_count_(0) {}

    void configure(int class_count)
    {
        class_count_ = std::max(1, class_count);
        tracks_.clear();
    }

    void update(const object_detect_result_list &input,
                const Options &opts,
                uint32_t image_width,
                uint32_t image_height,
                object_detect_result_list *output)
    {
        ensure_configured();
        for (size_t i = 0; i < tracks_.size(); ++i) {
            tracks_[i].matched_this_update = false;
        }

        std::vector<object_detect_result> candidates;
        candidates.reserve(std::max(0, input.count));
        for (int i = 0; i < input.count && i < OBJ_NUMB_MAX_SIZE; ++i) {
            object_detect_result det = input.results[i];
            if (det.box.right <= det.box.left || det.box.bottom <= det.box.top) {
                continue;
            }
            sanitize_box(&det.box, image_width, image_height);
            candidates.push_back(det);
        }
        std::sort(candidates.begin(), candidates.end(),
                  [](const object_detect_result &a, const object_detect_result &b) {
                      return a.prop > b.prop;
                  });

        for (size_t i = 0; i < candidates.size(); ++i) {
            const object_detect_result &candidate = candidates[i];
            int best_index = -1;
            bool best_already_matched = false;
            float best_score = -1.0f;
            for (size_t t = 0; t < tracks_.size(); ++t) {
                float match_score = 0.0f;
                if (!match_score_for(tracks_[t], candidate, opts, &match_score)) {
                    continue;
                }
                if (match_score > best_score) {
                    best_score = match_score;
                    best_index = static_cast<int>(t);
                    best_already_matched = tracks_[t].matched_this_update;
                }
            }

            if (best_index >= 0) {
                if (best_already_matched) {
                    vote_class(&tracks_[best_index], candidate, opts);
                } else {
                    update_track(&tracks_[best_index], candidate, opts, image_width, image_height);
                }
                continue;
            }

            create_track(candidate, opts, image_width, image_height);
        }

        std::vector<DefectTrack> next_tracks;
        next_tracks.reserve(tracks_.size());
        for (size_t i = 0; i < tracks_.size(); ++i) {
            DefectTrack track = tracks_[i];
            if (!track.matched_this_update) {
                track.missed += 1;
                track.consecutive_hits = 0;
                track.det.prop *= 0.90f;
            }
            if (track.missed <= opts.defect_hold) {
                next_tracks.push_back(track);
            }
        }
        tracks_.swap(next_tracks);

        fill_output(opts, output);
    }

    void fill_output(const Options &opts, object_detect_result_list *output) const
    {
        memset(output, 0, sizeof(*output));
        std::vector<object_detect_result> visible;
        visible.reserve(tracks_.size());
        for (size_t i = 0; i < tracks_.size(); ++i) {
            const DefectTrack &track = tracks_[i];
            if (!track.confirmed) {
                continue;
            }
            if (track.det.prop <= 0.001f) {
                continue;
            }
            visible.push_back(track.det);
        }
        std::sort(visible.begin(), visible.end(),
                  [](const object_detect_result &a, const object_detect_result &b) {
                      return a.prop > b.prop;
                  });
        for (size_t i = 0; i < visible.size() && output->count < OBJ_NUMB_MAX_SIZE; ++i) {
            output->results[output->count++] = visible[i];
        }
    }

private:
    int class_count_;
    std::vector<DefectTrack> tracks_;

    void ensure_configured()
    {
        if (class_count_ <= 0) {
            class_count_ = 4;
        }
    }

    bool match_score_for(const DefectTrack &track,
                         const object_detect_result &candidate,
                         const Options &opts,
                         float *score) const
    {
        const float iou = rect_iou(track.det.box, candidate.box);
        const float center_ratio = rect_center_distance_ratio(track.det.box, candidate.box);
        if (iou < opts.defect_match_iou && center_ratio > opts.defect_match_center) {
            return false;
        }
        const float center_bonus = opts.defect_match_center > 0.0f
                                       ? std::max(0.0f, 1.0f - center_ratio / opts.defect_match_center)
                                       : 0.0f;
        const float class_bonus = track.det.cls_id == candidate.cls_id ? 0.05f : 0.0f;
        *score = iou + 0.25f * center_bonus + class_bonus;
        return true;
    }

    void decay_votes(DefectTrack *track, const Options &opts)
    {
        const float decay = std::max(0.01f, std::min(opts.defect_class_decay, 0.99f));
        for (size_t i = 0; i < track->class_scores.size(); ++i) {
            track->class_scores[i] *= decay;
        }
    }

    void vote_class(DefectTrack *track, const object_detect_result &candidate, const Options &opts)
    {
        decay_votes(track, opts);
        if (candidate.cls_id >= 0 && candidate.cls_id < static_cast<int>(track->class_scores.size())) {
            track->class_scores[static_cast<size_t>(candidate.cls_id)] += std::max(0.001f, candidate.prop);
        }
        track->det.cls_id = stable_dominant_class(track->class_scores, track->det.cls_id,
                                                  candidate.cls_id);
    }

    void update_track(DefectTrack *track,
                      const object_detect_result &candidate,
                      const Options &opts,
                      uint32_t image_width,
                      uint32_t image_height)
    {
        const float alpha = std::max(0.01f, std::min(opts.defect_smooth_alpha, 1.0f));
        track->det.box.left = smooth_coord(track->det.box.left, candidate.box.left, alpha);
        track->det.box.top = smooth_coord(track->det.box.top, candidate.box.top, alpha);
        track->det.box.right = smooth_coord(track->det.box.right, candidate.box.right, alpha);
        track->det.box.bottom = smooth_coord(track->det.box.bottom, candidate.box.bottom, alpha);
        sanitize_box(&track->det.box, image_width, image_height);
        track->det.prop = track->det.prop * (1.0f - alpha) + candidate.prop * alpha;
        track->hits += 1;
        track->consecutive_hits += 1;
        if (track->consecutive_hits >= opts.defect_confirm) {
            track->confirmed = true;
        }
        track->missed = 0;
        track->matched_this_update = true;
        vote_class(track, candidate, opts);
    }

    void create_track(const object_detect_result &candidate,
                      const Options &opts,
                      uint32_t image_width,
                      uint32_t image_height)
    {
        DefectTrack track;
        track.det = candidate;
        sanitize_box(&track.det.box, image_width, image_height);
        track.class_scores.assign(static_cast<size_t>(class_count_), 0.0f);
        if (candidate.cls_id >= 0 && candidate.cls_id < class_count_) {
            track.class_scores[static_cast<size_t>(candidate.cls_id)] = std::max(0.001f, candidate.prop);
        }
        track.det.cls_id = dominant_class(track.class_scores, candidate.cls_id);
        track.hits = 1;
        track.consecutive_hits = 1;
        track.confirmed = track.consecutive_hits >= opts.defect_confirm;
        track.missed = 0;
        track.matched_this_update = true;
        tracks_.push_back(track);
    }
};

class SegDefectTemporalFilter {
public:
    SegDefectTemporalFilter() : class_count_(0) {}

    void configure(int class_count)
    {
        class_count_ = std::max(1, class_count);
        tracks_.clear();
    }

    void update(const object_seg_result_list &seg_input,
                const object_detect_result_list &bbox_input,
                const Options &opts,
                uint32_t image_width,
                uint32_t image_height,
                object_detect_result_list *det_output,
                object_seg_result_list *seg_output)
    {
        ensure_configured();
        for (size_t i = 0; i < tracks_.size(); ++i) {
            tracks_[i].matched_this_update = false;
        }

        std::vector<object_seg_result> candidates;
        candidates.reserve(std::max(0, seg_input.count));
        for (int i = 0; i < seg_input.count && i < OBJ_NUMB_MAX_SIZE; ++i) {
            object_seg_result seg = seg_input.results[i];
            if (i < bbox_input.count && i < OBJ_NUMB_MAX_SIZE) {
                seg.det = bbox_input.results[i];
            }
            if (seg.det.box.right <= seg.det.box.left || seg.det.box.bottom <= seg.det.box.top) {
                continue;
            }
            sanitize_box(&seg.det.box, image_width, image_height);
            candidates.push_back(seg);
        }
        std::sort(candidates.begin(), candidates.end(),
                  [](const object_seg_result &a, const object_seg_result &b) {
                      return a.det.prop > b.det.prop;
                  });

        for (size_t i = 0; i < candidates.size(); ++i) {
            const object_seg_result &candidate = candidates[i];
            int best_index = -1;
            bool best_already_matched = false;
            float best_score = -1.0f;
            for (size_t t = 0; t < tracks_.size(); ++t) {
                float match_score = 0.0f;
                if (!match_score_for(tracks_[t], candidate.det, opts, &match_score)) {
                    continue;
                }
                if (match_score > best_score) {
                    best_score = match_score;
                    best_index = static_cast<int>(t);
                    best_already_matched = tracks_[t].matched_this_update;
                }
            }

            if (best_index >= 0) {
                if (best_already_matched) {
                    vote_class(&tracks_[best_index], candidate.det, opts);
                } else {
                    update_track(&tracks_[best_index], candidate, opts, image_width, image_height);
                }
                continue;
            }

            create_track(candidate, opts, image_width, image_height);
        }

        std::vector<SegDefectTrack> next_tracks;
        next_tracks.reserve(tracks_.size());
        for (size_t i = 0; i < tracks_.size(); ++i) {
            SegDefectTrack track = tracks_[i];
            if (!track.matched_this_update) {
                track.missed += 1;
                track.consecutive_hits = 0;
                track.det.prop *= 0.90f;
            }
            if (track.missed <= opts.defect_hold) {
                next_tracks.push_back(track);
            }
        }
        tracks_.swap(next_tracks);

        fill_output(seg_input.mask_status, det_output, seg_output);
    }

private:
    int class_count_;
    std::vector<SegDefectTrack> tracks_;

    void ensure_configured()
    {
        if (class_count_ <= 0) {
            class_count_ = 4;
        }
    }

    bool match_score_for(const SegDefectTrack &track,
                         const object_detect_result &candidate,
                         const Options &opts,
                         float *score) const
    {
        const float iou = rect_iou(track.det.box, candidate.box);
        const float center_ratio = rect_center_distance_ratio(track.det.box, candidate.box);
        if (iou < opts.defect_match_iou && center_ratio > opts.defect_match_center) {
            return false;
        }
        const float center_bonus = opts.defect_match_center > 0.0f
                                       ? std::max(0.0f, 1.0f - center_ratio / opts.defect_match_center)
                                       : 0.0f;
        const float class_bonus = track.det.cls_id == candidate.cls_id ? 0.05f : 0.0f;
        *score = iou + 0.25f * center_bonus + class_bonus;
        return true;
    }

    void decay_votes(SegDefectTrack *track, const Options &opts)
    {
        const float decay = std::max(0.01f, std::min(opts.defect_class_decay, 0.99f));
        for (size_t i = 0; i < track->class_scores.size(); ++i) {
            track->class_scores[i] *= decay;
        }
    }

    void vote_class(SegDefectTrack *track, const object_detect_result &candidate, const Options &opts)
    {
        decay_votes(track, opts);
        if (candidate.cls_id >= 0 && candidate.cls_id < static_cast<int>(track->class_scores.size())) {
            track->class_scores[static_cast<size_t>(candidate.cls_id)] += std::max(0.001f, candidate.prop);
        }
        track->det.cls_id = stable_dominant_class(track->class_scores, track->det.cls_id,
                                                  candidate.cls_id);
    }

    void update_track(SegDefectTrack *track,
                      const object_seg_result &candidate,
                      const Options &opts,
                      uint32_t image_width,
                      uint32_t image_height)
    {
        const float alpha = std::max(0.01f, std::min(opts.defect_smooth_alpha, 1.0f));
        track->det.box.left = smooth_coord(track->det.box.left, candidate.det.box.left, alpha);
        track->det.box.top = smooth_coord(track->det.box.top, candidate.det.box.top, alpha);
        track->det.box.right = smooth_coord(track->det.box.right, candidate.det.box.right, alpha);
        track->det.box.bottom = smooth_coord(track->det.box.bottom, candidate.det.box.bottom, alpha);
        sanitize_box(&track->det.box, image_width, image_height);
        track->det.prop = track->det.prop * (1.0f - alpha) + candidate.det.prop * alpha;
        track->hits += 1;
        track->consecutive_hits += 1;
        if (track->consecutive_hits >= opts.defect_confirm) {
            track->confirmed = true;
        }
        track->missed = 0;
        track->matched_this_update = true;
        track->seg = candidate;
        vote_class(track, candidate.det, opts);
    }

    void create_track(const object_seg_result &candidate,
                      const Options &opts,
                      uint32_t image_width,
                      uint32_t image_height)
    {
        SegDefectTrack track;
        track.det = candidate.det;
        sanitize_box(&track.det.box, image_width, image_height);
        track.seg = candidate;
        track.class_scores.assign(static_cast<size_t>(class_count_), 0.0f);
        if (candidate.det.cls_id >= 0 && candidate.det.cls_id < class_count_) {
            track.class_scores[static_cast<size_t>(candidate.det.cls_id)] =
                std::max(0.001f, candidate.det.prop);
        }
        track.det.cls_id = dominant_class(track.class_scores, candidate.det.cls_id);
        track.hits = 1;
        track.consecutive_hits = 1;
        track.confirmed = track.consecutive_hits >= opts.defect_confirm;
        track.missed = 0;
        track.matched_this_update = true;
        tracks_.push_back(track);
    }

    void fill_output(int mask_status,
                     object_detect_result_list *det_output,
                     object_seg_result_list *seg_output) const
    {
        memset(det_output, 0, sizeof(*det_output));
        memset(seg_output, 0, sizeof(*seg_output));
        seg_output->mask_status = mask_status;

        std::vector<SegDefectTrack> visible;
        visible.reserve(tracks_.size());
        for (size_t i = 0; i < tracks_.size(); ++i) {
            const SegDefectTrack &track = tracks_[i];
            if (!track.confirmed) {
                continue;
            }
            if (track.det.prop <= 0.001f) {
                continue;
            }
            visible.push_back(track);
        }
        std::sort(visible.begin(), visible.end(),
                  [](const SegDefectTrack &a, const SegDefectTrack &b) {
                      return a.det.prop > b.det.prop;
                  });

        for (size_t i = 0; i < visible.size() && det_output->count < OBJ_NUMB_MAX_SIZE; ++i) {
            const SegDefectTrack &track = visible[i];
            object_seg_result seg = track.seg;
            seg.det = track.det;
            det_output->results[det_output->count++] = track.det;
            seg_output->results[seg_output->count++] = seg;
        }
    }
};

static void append_detection(object_detect_result_list *dst,
                             const object_detect_result &src,
                             int class_offset,
                             uint32_t image_width,
                             uint32_t image_height)
{
    if (dst->count >= OBJ_NUMB_MAX_SIZE) {
        return;
    }

    const int max_x = static_cast<int>(image_width) - 1;
    const int max_y = static_cast<int>(image_height) - 1;
    object_detect_result *out = &dst->results[dst->count++];
    *out = src;
    out->cls_id = src.cls_id + class_offset;
    out->box.left = clamp_i32(out->box.left, 0, max_x);
    out->box.right = clamp_i32(out->box.right, 0, max_x);
    out->box.top = clamp_i32(out->box.top, 0, max_y);
    out->box.bottom = clamp_i32(out->box.bottom, 0, max_y);
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
    int seg_sidecar_fd = -1;
    bool post_process_ready = false;
    bool camera_started = false;
    CameraContext camera;
    rknn_app_context_t rknn_app_ctx;
    rknn_app_context_t defect_app_ctx;
    DefectTemporalFilter defect_filter;
    SegDefectTemporalFilter seg_defect_filter;
    InputAdjustRuntime input_adjust;
    memset(&rknn_app_ctx, 0, sizeof(rknn_app_ctx));
    memset(&defect_app_ctx, 0, sizeof(defect_app_ctx));

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
    TemporalBoxState chip_box_state;
    TemporalObbState chip_obb_state;
    object_detect_result_list cached_defect_results;
    memset(&cached_defect_results, 0, sizeof(cached_defect_results));
    bool has_cached_defect_results = false;
    object_seg_result_list cached_seg_results;
    memset(&cached_seg_results, 0, sizeof(cached_seg_results));
    bool has_cached_seg_results = false;

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
    rknn_app_ctx.box_conf_threshold = opts.two_stage ? opts.chip_conf_threshold : opts.conf_threshold;
    rknn_app_ctx.nms_threshold = opts.nms_threshold;

    if (opts.two_stage) {
        if (init_yolo11_model(opts.defect_model.c_str(), &defect_app_ctx) != 0) {
            fprintf(stderr, "init_yolo11_model failed: %s\n", opts.defect_model.c_str());
            exit_code = 1;
            goto out;
        }
        defect_app_ctx.box_conf_threshold = opts.defect_conf_threshold;
        defect_app_ctx.nms_threshold = opts.nms_threshold;
        defect_filter.configure(defect_app_ctx.class_count);
        seg_defect_filter.configure(defect_app_ctx.class_count);
        if (opts.defect_model_kind == YOLO_MODEL_KIND_SEG) {
            fprintf(stderr,
                    "defect model kind=seg: YOLOv8-seg mask contour postprocess is enabled\n");
        }
    }

    if (!opts.seg_sidecar.empty()) {
        seg_sidecar_fd = open(opts.seg_sidecar.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (seg_sidecar_fd < 0) {
            fprintf(stderr, "open --seg-sidecar failed: %s: %s\n",
                    opts.seg_sidecar.c_str(), strerror(errno));
            exit_code = 1;
            goto out;
        }
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

    fprintf(stderr,
            "streaming %s packets to stdout: frames=%u skip=%u payload=%zu conf=%.3f nms=%.3f roi=%s",
            LIVE_APP_NAME, opts.frames, opts.skip, frame_size,
            opts.conf_threshold, opts.nms_threshold, opts.roi_enabled ? "on" : "off");
    if (opts.roi_enabled) {
        fprintf(stderr, ":%u,%u,%u,%u", opts.roi_x, opts.roi_y, opts.roi_w, opts.roi_h);
    }
    if (opts.two_stage) {
        fprintf(stderr,
                " two_stage=on chip_model_kind=%s defect_model_kind=%s chip_conf=%.3f defect_conf=%.3f roi_margin=%.3f roi_smooth_alpha=%.3f roi_hold=%u chip_interval=%u defect_interval=%u defect_confirm=%u defect_hold=%u defect_smooth_alpha=%.3f defect_match_iou=%.3f defect_match_center=%.3f defect_class_decay=%.3f",
                model_kind_name(opts.chip_model_kind),
                model_kind_name(opts.defect_model_kind),
                opts.chip_conf_threshold, opts.defect_conf_threshold, opts.roi_margin,
                opts.roi_smooth_alpha, opts.roi_hold, opts.chip_interval, opts.defect_interval,
                opts.defect_confirm, opts.defect_hold, opts.defect_smooth_alpha,
                opts.defect_match_iou, opts.defect_match_center, opts.defect_class_decay);
    }
    if (seg_sidecar_fd >= 0) {
        fprintf(stderr, " seg_sidecar=%s protocol=RYLSv%u stdout_protocol=RYL1",
                opts.seg_sidecar.c_str(), kSegSidecarVersion);
    }
    if (opts.input_adjust_enabled) {
        fprintf(stderr,
                " input_adjust=on brightness=%d contrast=%.3f gamma=%.3f saturation=%.3f sharpness=%.3f adjust_file=%s",
                opts.input_brightness, opts.input_contrast, opts.input_gamma,
                opts.input_saturation, opts.input_sharpness, opts.input_adjust_file.c_str());
    } else {
        fprintf(stderr, " input_adjust=off");
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

        if (image.format == IMAGE_FORMAT_RGB888) {
            refresh_input_adjust_runtime(opts, &input_adjust);
            apply_input_adjustment(image.virt_addr,
                                   static_cast<uint32_t>(image.width),
                                   static_cast<uint32_t>(image.height),
                                   &input_adjust);
            rgb_to_nv12(image.virt_addr,
                        static_cast<uint32_t>(image.width),
                        static_cast<uint32_t>(image.height),
                        &frame);
        } else if (opts.input_adjust_enabled && emitted == 0) {
            fprintf(stderr, "input_adjust ignored for non-RGB888 input format=%d\n", image.format);
        }

        object_detect_result_list od_results;
        memset(&od_results, 0, sizeof(od_results));
        object_obb_result current_chip_obb;
        memset(&current_chip_obb, 0, sizeof(current_chip_obb));
        bool have_current_chip_obb = false;
        if (opts.two_stage) {
            object_detect_result chip_box;
            memset(&chip_box, 0, sizeof(chip_box));
            bool have_chip_box = false;
            if (opts.chip_model_kind == YOLO_MODEL_KIND_OBB) {
                object_obb_result chip_obb;
                memset(&chip_obb, 0, sizeof(chip_obb));
                bool have_chip_obb = false;
                const bool should_run_chip = !chip_obb_state.has_box ||
                                             opts.chip_interval <= 1 ||
                                             (emitted % opts.chip_interval) == 0;
                if (should_run_chip) {
                    object_obb_result_list chip_obb_results;
                    object_detect_result_list chip_bbox_results;
                    memset(&chip_obb_results, 0, sizeof(chip_obb_results));
                    memset(&chip_bbox_results, 0, sizeof(chip_bbox_results));
                    const int chip_ret = inference_yolo11_obb_model(&rknn_app_ctx, &image,
                                                                    &chip_obb_results,
                                                                    &chip_bbox_results);
                    if (chip_ret != 0) {
                        fprintf(stderr, "chip OBB inference failed: ret=%d frame=%u\n", chip_ret, emitted);
                        exit_code = 1;
                        queue_buffer(&camera, buf.index);
                        break;
                    }

                    object_obb_result detected_chip_obb;
                    memset(&detected_chip_obb, 0, sizeof(detected_chip_obb));
                    if (select_primary_chip_obb(chip_obb_results, &detected_chip_obb)) {
                        chip_obb = smooth_chip_obb_detection(&chip_obb_state, detected_chip_obb,
                                                             opts.roi_smooth_alpha, opts.width, opts.height);
                        have_chip_obb = true;
                    } else if (hold_chip_obb_detection(&chip_obb_state, opts.roi_hold, &chip_obb)) {
                        have_chip_obb = true;
                    }
                } else if (reuse_chip_obb_detection(chip_obb_state, &chip_obb)) {
                    have_chip_obb = true;
                }

                if (have_chip_obb) {
                    current_chip_obb = chip_obb;
                    have_current_chip_obb = true;
                    chip_box = obb_to_detection(chip_obb);
                    have_chip_box = true;
                }
            } else {
                const bool should_run_chip = !chip_box_state.has_box ||
                                             opts.chip_interval <= 1 ||
                                             (emitted % opts.chip_interval) == 0;
                if (should_run_chip) {
                    object_detect_result_list chip_results;
                    memset(&chip_results, 0, sizeof(chip_results));
                    const int chip_ret = inference_yolo11_model(&rknn_app_ctx, &image, &chip_results);
                    if (chip_ret != 0) {
                        fprintf(stderr, "chip inference failed: ret=%d frame=%u\n", chip_ret, emitted);
                        exit_code = 1;
                        queue_buffer(&camera, buf.index);
                        break;
                    }

                    object_detect_result detected_chip_box;
                    memset(&detected_chip_box, 0, sizeof(detected_chip_box));
                    if (select_primary_chip(chip_results, &detected_chip_box)) {
                        chip_box = smooth_chip_detection(&chip_box_state, detected_chip_box,
                                                         opts.roi_smooth_alpha, opts.width, opts.height);
                        have_chip_box = true;
                    } else if (hold_chip_detection(&chip_box_state, opts.roi_hold, &chip_box)) {
                        have_chip_box = true;
                    }
                } else if (reuse_chip_detection(chip_box_state, &chip_box)) {
                    have_chip_box = true;
                }
            }

            if (have_chip_box) {
                append_detection(&od_results, chip_box, 0, opts.width, opts.height);

                const bool should_run_defect = !has_cached_defect_results ||
                                               opts.defect_interval <= 1 ||
                                               (emitted % opts.defect_interval) == 0;
                if (should_run_defect) {
                    image_buffer_t defect_image;
                    uint32_t defect_offset_x = 0;
                    uint32_t defect_offset_y = 0;
                    AffineTransform crop_to_src;
                    const bool use_obb_crop = have_current_chip_obb &&
                                              opts.chip_model_kind == YOLO_MODEL_KIND_OBB;
                    bool crop_ok = false;
                    if (use_obb_crop) {
                        crop_ok = crop_rgb_obb(image, current_chip_obb, opts.roi_margin,
                                               &roi_rgb_frame, &defect_image,
                                               &crop_to_src);
                    } else {
                        crop_ok = crop_rgb_rect(image, chip_box.box, opts.roi_margin,
                                                &roi_rgb_frame, &defect_image,
                                                &defect_offset_x, &defect_offset_y);
                    }
                    if (!crop_ok) {
                        exit_code = 1;
                        queue_buffer(&camera, buf.index);
                        break;
                    }

                    object_detect_result_list defect_results;
                    memset(&defect_results, 0, sizeof(defect_results));
                    int defect_ret = 0;
                    if (opts.defect_model_kind == YOLO_MODEL_KIND_SEG) {
                        object_seg_result_list defect_seg_results;
                        memset(&defect_seg_results, 0, sizeof(defect_seg_results));
                        defect_ret = inference_yolo11_seg_model(&defect_app_ctx, &defect_image,
                                                                &defect_seg_results, &defect_results);
                        if (defect_ret == 0) {
                            if (use_obb_crop) {
                                map_results_from_crop(&defect_results, crop_to_src, opts.width, opts.height);
                                map_seg_results_from_crop(&defect_seg_results, crop_to_src, opts.width, opts.height);
                            } else {
                                translate_results_from_roi(&defect_results, defect_offset_x, defect_offset_y,
                                                           opts.width, opts.height);
                                translate_seg_results_from_roi(&defect_seg_results, defect_offset_x, defect_offset_y,
                                                               opts.width, opts.height);
                            }
                            seg_defect_filter.update(defect_seg_results, defect_results, opts,
                                                     opts.width, opts.height,
                                                     &cached_defect_results, &cached_seg_results);
                            has_cached_defect_results = true;
                            has_cached_seg_results = true;
                        }
                    } else {
                        defect_ret = inference_yolo11_model(&defect_app_ctx, &defect_image, &defect_results);
                        if (defect_ret == 0) {
                            if (use_obb_crop) {
                                map_results_from_crop(&defect_results, crop_to_src, opts.width, opts.height);
                            } else {
                                translate_results_from_roi(&defect_results, defect_offset_x, defect_offset_y,
                                                           opts.width, opts.height);
                            }
                            defect_filter.update(defect_results, opts, opts.width, opts.height,
                                                 &cached_defect_results);
                            has_cached_defect_results = true;
                            has_cached_seg_results = false;
                        }
                    }
                    if (defect_ret != 0) {
                        fprintf(stderr, "defect inference failed: ret=%d frame=%u\n", defect_ret, emitted);
                        exit_code = 1;
                        queue_buffer(&camera, buf.index);
                        break;
                    }
                }
                if (has_cached_defect_results) {
                    for (int i = 0; i < cached_defect_results.count && i < OBJ_NUMB_MAX_SIZE; ++i) {
                        append_detection(&od_results, cached_defect_results.results[i], 1, opts.width, opts.height);
                    }
                }
            }
        } else {
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
        }

        const object_seg_result_list *seg_contours = has_cached_seg_results ? &cached_seg_results : NULL;
        const object_obb_result *chip_obb_contour = have_current_chip_obb ? &current_chip_obb : NULL;
        const bool wrote_frame = opts.stream_contours && (seg_contours != NULL || chip_obb_contour != NULL)
                                     ? write_frame_packet_with_mixed_contours(stream_fd, opts.width, opts.height,
                                                                              emitted, od_results, seg_contours,
                                                                              chip_obb_contour, frame)
                                     : write_frame_packet(stream_fd, opts.width, opts.height, emitted, od_results, frame);
        if (!wrote_frame) {
            fprintf(stderr, "write stream failed: %s\n", strerror(errno));
            exit_code = 1;
            queue_buffer(&camera, buf.index);
            break;
        }
        if (seg_sidecar_fd >= 0 &&
            !write_seg_sidecar_packet(seg_sidecar_fd, opts.width, opts.height, emitted, od_results)) {
            fprintf(stderr, "write segmentation sidecar failed: %s\n", strerror(errno));
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
    release_yolo11_model(&defect_app_ctx);
    release_yolo11_model(&rknn_app_ctx);
    if (post_process_ready) {
        deinit_post_process();
    }
    if (seg_sidecar_fd >= 0) {
        close(seg_sidecar_fd);
    }
    close(stream_fd);
    return exit_code;
}
