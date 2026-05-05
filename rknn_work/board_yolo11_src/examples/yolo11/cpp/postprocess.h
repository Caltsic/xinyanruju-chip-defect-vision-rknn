#ifndef _RKNN_YOLO11_DEMO_POSTPROCESS_H_
#define _RKNN_YOLO11_DEMO_POSTPROCESS_H_

#include <stdint.h>
#include <vector>
#include "rknn_api.h"
#include "common.h"
#include "image_utils.h"

#define OBJ_NAME_MAX_SIZE 64
#define OBJ_NUMB_MAX_SIZE 128

#ifndef OBJ_CLASS_NUM
#define OBJ_CLASS_NUM 80
#endif

#ifndef NMS_THRESH
#define NMS_THRESH 0.45
#endif

#ifndef BOX_THRESH
#define BOX_THRESH 0.25
#endif

// class rknn_app_context_t;

typedef struct {
    image_rect_t box;
    float prop;
    int cls_id;
} object_detect_result;

typedef struct {
    int x;
    int y;
} object_seg_point;

typedef struct {
    int count;
    object_seg_point points[64];
} object_seg_contour;

typedef struct {
    object_detect_result det;
    int has_mask;
    int mask_width;
    int mask_height;
    int contour_count;
    object_seg_contour contours[4];
} object_seg_result;

typedef struct {
    int id;
    int count;
    object_detect_result results[OBJ_NUMB_MAX_SIZE];
} object_detect_result_list;

typedef struct {
    int id;
    int count;
    int mask_status;
    object_seg_result results[OBJ_NUMB_MAX_SIZE];
} object_seg_result_list;

typedef enum {
    YOLO_MODEL_KIND_DETECT = 0,
    YOLO_MODEL_KIND_SEG = 1,
} yolo_model_kind_t;

int init_post_process();
void deinit_post_process();
char *coco_cls_to_name(int cls_id);
int post_process(rknn_app_context_t *app_ctx, void *outputs, letterbox_t *letter_box, float conf_threshold, float nms_threshold, object_detect_result_list *od_results);
int post_process_seg(rknn_app_context_t *app_ctx, void *outputs, letterbox_t *letter_box, float conf_threshold, float nms_threshold, object_seg_result_list *seg_results, object_detect_result_list *bbox_fallback);

void deinitPostProcess();
#endif //_RKNN_YOLO11_DEMO_POSTPROCESS_H_
