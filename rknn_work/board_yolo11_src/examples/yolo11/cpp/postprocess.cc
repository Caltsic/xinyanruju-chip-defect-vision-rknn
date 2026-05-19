// Copyright (c) 2024 by Rockchip Electronics Co., Ltd. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "yolo11.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

#include <algorithm>
#include <set>
#include <vector>
#ifndef YOLO_LABEL_TXT_PATH
#define YOLO_LABEL_TXT_PATH "./model/coco_80_labels_list.txt"
#endif

#define LABEL_NALE_TXT_PATH YOLO_LABEL_TXT_PATH

static char *labels[OBJ_CLASS_NUM];

inline static int clamp(float val, int min, int max) { return val > min ? (val < max ? val : max) : min; }

static char *readLine(FILE *fp, char *buffer, int *len)
{
    int ch;
    int i = 0;
    size_t buff_len = 0;

    buffer = (char *)malloc(buff_len + 1);
    if (!buffer)
        return NULL; // Out of memory

    while ((ch = fgetc(fp)) != '\n' && ch != EOF)
    {
        buff_len++;
        void *tmp = realloc(buffer, buff_len + 1);
        if (tmp == NULL)
        {
            free(buffer);
            return NULL; // Out of memory
        }
        buffer = (char *)tmp;

        buffer[i] = (char)ch;
        i++;
    }
    buffer[i] = '\0';

    *len = buff_len;

    // Detect end
    if (ch == EOF && (i == 0 || ferror(fp)))
    {
        free(buffer);
        return NULL;
    }
    return buffer;
}

static int readLines(const char *fileName, char *lines[], int max_line)
{
    FILE *file = fopen(fileName, "r");
    char *s;
    int i = 0;
    int n = 0;

    if (file == NULL)
    {
        printf("Open %s fail!\n", fileName);
        return -1;
    }

    while ((s = readLine(file, s, &n)) != NULL)
    {
        lines[i++] = s;
        if (i >= max_line)
            break;
    }
    fclose(file);
    return i;
}

static int loadLabelName(const char *locationFilename, char *label[])
{
    printf("load lable %s\n", locationFilename);
    readLines(locationFilename, label, OBJ_CLASS_NUM);
    return 0;
}

static float CalculateOverlap(float xmin0, float ymin0, float xmax0, float ymax0, float xmin1, float ymin1, float xmax1,
                              float ymax1)
{
    float w = fmax(0.f, fmin(xmax0, xmax1) - fmax(xmin0, xmin1) + 1.0);
    float h = fmax(0.f, fmin(ymax0, ymax1) - fmax(ymin0, ymin1) + 1.0);
    float i = w * h;
    float u = (xmax0 - xmin0 + 1.0) * (ymax0 - ymin0 + 1.0) + (xmax1 - xmin1 + 1.0) * (ymax1 - ymin1 + 1.0) - i;
    return u <= 0.f ? 0.f : (i / u);
}

static int nms(int validCount, std::vector<float> &outputLocations, std::vector<int> classIds, std::vector<int> &order,
               int filterId, float threshold)
{
    for (int i = 0; i < validCount; ++i)
    {
        int n = order[i];
        if (n == -1 || classIds[n] != filterId)
        {
            continue;
        }
        for (int j = i + 1; j < validCount; ++j)
        {
            int m = order[j];
            if (m == -1 || classIds[m] != filterId)
            {
                continue;
            }
            float xmin0 = outputLocations[n * 4 + 0];
            float ymin0 = outputLocations[n * 4 + 1];
            float xmax0 = outputLocations[n * 4 + 0] + outputLocations[n * 4 + 2];
            float ymax0 = outputLocations[n * 4 + 1] + outputLocations[n * 4 + 3];

            float xmin1 = outputLocations[m * 4 + 0];
            float ymin1 = outputLocations[m * 4 + 1];
            float xmax1 = outputLocations[m * 4 + 0] + outputLocations[m * 4 + 2];
            float ymax1 = outputLocations[m * 4 + 1] + outputLocations[m * 4 + 3];

            float iou = CalculateOverlap(xmin0, ymin0, xmax0, ymax0, xmin1, ymin1, xmax1, ymax1);

            if (iou > threshold)
            {
                order[j] = -1;
            }
        }
    }
    return 0;
}

static int quick_sort_indice_inverse(std::vector<float> &input, int left, int right, std::vector<int> &indices)
{
    float key;
    int key_index;
    int low = left;
    int high = right;
    if (left < right)
    {
        key_index = indices[left];
        key = input[left];
        while (low < high)
        {
            while (low < high && input[high] <= key)
            {
                high--;
            }
            input[low] = input[high];
            indices[low] = indices[high];
            while (low < high && input[low] >= key)
            {
                low++;
            }
            input[high] = input[low];
            indices[high] = indices[low];
        }
        input[low] = key;
        indices[low] = key_index;
        quick_sort_indice_inverse(input, left, low - 1, indices);
        quick_sort_indice_inverse(input, low + 1, right, indices);
    }
    return low;
}

static float sigmoid(float x) { return 1.0 / (1.0 + expf(-x)); }

static float unsigmoid(float y) { return -1.0 * logf((1.0 / y) - 1.0); }

inline static int32_t __clip(float val, float min, float max)
{
    float f = val <= min ? min : (val >= max ? max : val);
    return f;
}

static int8_t qnt_f32_to_affine(float f32, int32_t zp, float scale)
{
    float dst_val = (f32 / scale) + zp;
    int8_t res = (int8_t)__clip(dst_val, -128, 127);
    return res;
}

static uint8_t qnt_f32_to_affine_u8(float f32, int32_t zp, float scale)
{
    float dst_val = (f32 / scale) + zp;
    uint8_t res = (uint8_t)__clip(dst_val, 0, 255);
    return res;
}

static float deqnt_affine_to_f32(int8_t qnt, int32_t zp, float scale) { return ((float)qnt - (float)zp) * scale; }

static float deqnt_affine_u8_to_f32(uint8_t qnt, int32_t zp, float scale) { return ((float)qnt - (float)zp) * scale; }

static void compute_dfl(float* tensor, int dfl_len, float* box){
    for (int b=0; b<4; b++){
        float exp_t[dfl_len];
        float exp_sum=0;
        float acc_sum=0;
        for (int i=0; i< dfl_len; i++){
            exp_t[i] = exp(tensor[i+b*dfl_len]);
            exp_sum += exp_t[i];
        }
        
        for (int i=0; i< dfl_len; i++){
            acc_sum += exp_t[i]/exp_sum *i;
        }
        box[b] = acc_sum;
    }
}

static int process_u8(uint8_t *box_tensor, int32_t box_zp, float box_scale,
                      uint8_t *score_tensor, int32_t score_zp, float score_scale,
                      uint8_t *score_sum_tensor, int32_t score_sum_zp, float score_sum_scale,
                      int grid_h, int grid_w, int stride, int dfl_len,
                      std::vector<float> &boxes,
                      std::vector<float> &objProbs,
                      std::vector<int> &classId,
                      float threshold)
{
    int validCount = 0;
    int grid_len = grid_h * grid_w;
    uint8_t score_thres_u8 = qnt_f32_to_affine_u8(threshold, score_zp, score_scale);
    uint8_t score_sum_thres_u8 = qnt_f32_to_affine_u8(threshold, score_sum_zp, score_sum_scale);

    for (int i = 0; i < grid_h; i++)
    {
        for (int j = 0; j < grid_w; j++)
        {
            int offset = i * grid_w + j;
            int max_class_id = -1;

            // Use score sum to quickly filter
            if (score_sum_tensor != nullptr)
            {
                if (score_sum_tensor[offset] < score_sum_thres_u8)
                {
                    continue;
                }
            }

            uint8_t max_score = -score_zp;
            for (int c = 0; c < OBJ_CLASS_NUM; c++)
            {
                if ((score_tensor[offset] > score_thres_u8) && (score_tensor[offset] > max_score))
                {
                    max_score = score_tensor[offset];
                    max_class_id = c;
                }
                offset += grid_len;
            }

            // compute box
            if (max_score > score_thres_u8)
            {
                offset = i * grid_w + j;
                float box[4];
                float before_dfl[dfl_len * 4];
                for (int k = 0; k < dfl_len * 4; k++)
                {
                    before_dfl[k] = deqnt_affine_u8_to_f32(box_tensor[offset], box_zp, box_scale);
                    offset += grid_len;
                }
                compute_dfl(before_dfl, dfl_len, box);

                float x1, y1, x2, y2, w, h;
                x1 = (-box[0] + j + 0.5) * stride;
                y1 = (-box[1] + i + 0.5) * stride;
                x2 = (box[2] + j + 0.5) * stride;
                y2 = (box[3] + i + 0.5) * stride;
                w = x2 - x1;
                h = y2 - y1;
                boxes.push_back(x1);
                boxes.push_back(y1);
                boxes.push_back(w);
                boxes.push_back(h);

                objProbs.push_back(deqnt_affine_u8_to_f32(max_score, score_zp, score_scale));
                classId.push_back(max_class_id);
                validCount++;
            }
        }
    }
    return validCount;
}

static int process_i8(int8_t *box_tensor, int32_t box_zp, float box_scale,
                      int8_t *score_tensor, int32_t score_zp, float score_scale,
                      int8_t *score_sum_tensor, int32_t score_sum_zp, float score_sum_scale,
                      int grid_h, int grid_w, int stride, int dfl_len,
                      std::vector<float> &boxes, 
                      std::vector<float> &objProbs, 
                      std::vector<int> &classId, 
                      float threshold)
{
    int validCount = 0;
    int grid_len = grid_h * grid_w;
    int8_t score_thres_i8 = qnt_f32_to_affine(threshold, score_zp, score_scale);
    int8_t score_sum_thres_i8 = qnt_f32_to_affine(threshold, score_sum_zp, score_sum_scale);

    for (int i = 0; i < grid_h; i++)
    {
        for (int j = 0; j < grid_w; j++)
        {
            int offset = i* grid_w + j;
            int max_class_id = -1;

            // 通过 score sum 起到快速过滤的作用
            if (score_sum_tensor != nullptr){
                if (score_sum_tensor[offset] < score_sum_thres_i8){
                    continue;
                }
            }

            int8_t max_score = -score_zp;
            for (int c= 0; c< OBJ_CLASS_NUM; c++){
                if ((score_tensor[offset] > score_thres_i8) && (score_tensor[offset] > max_score))
                {
                    max_score = score_tensor[offset];
                    max_class_id = c;
                }
                offset += grid_len;
            }

            // compute box
            if (max_score> score_thres_i8){
                offset = i* grid_w + j;
                float box[4];
                float before_dfl[dfl_len*4];
                for (int k=0; k< dfl_len*4; k++){
                    before_dfl[k] = deqnt_affine_to_f32(box_tensor[offset], box_zp, box_scale);
                    offset += grid_len;
                }
                compute_dfl(before_dfl, dfl_len, box);

                float x1,y1,x2,y2,w,h;
                x1 = (-box[0] + j + 0.5)*stride;
                y1 = (-box[1] + i + 0.5)*stride;
                x2 = (box[2] + j + 0.5)*stride;
                y2 = (box[3] + i + 0.5)*stride;
                w = x2 - x1;
                h = y2 - y1;
                boxes.push_back(x1);
                boxes.push_back(y1);
                boxes.push_back(w);
                boxes.push_back(h);

                objProbs.push_back(deqnt_affine_to_f32(max_score, score_zp, score_scale));
                classId.push_back(max_class_id);
                validCount ++;
            }
        }
    }
    return validCount;
}

static int process_fp32(float *box_tensor, float *score_tensor, float *score_sum_tensor, 
                        int grid_h, int grid_w, int stride, int dfl_len,
                        std::vector<float> &boxes, 
                        std::vector<float> &objProbs, 
                        std::vector<int> &classId, 
                        float threshold)
{
    int validCount = 0;
    int grid_len = grid_h * grid_w;
    for (int i = 0; i < grid_h; i++)
    {
        for (int j = 0; j < grid_w; j++)
        {
            int offset = i* grid_w + j;
            int max_class_id = -1;

            // 通过 score sum 起到快速过滤的作用
            if (score_sum_tensor != nullptr){
                if (score_sum_tensor[offset] < threshold){
                    continue;
                }
            }

            float max_score = 0;
            for (int c= 0; c< OBJ_CLASS_NUM; c++){
                if ((score_tensor[offset] > threshold) && (score_tensor[offset] > max_score))
                {
                    max_score = score_tensor[offset];
                    max_class_id = c;
                }
                offset += grid_len;
            }

            // compute box
            if (max_score> threshold){
                offset = i* grid_w + j;
                float box[4];
                float before_dfl[dfl_len*4];
                for (int k=0; k< dfl_len*4; k++){
                    before_dfl[k] = box_tensor[offset];
                    offset += grid_len;
                }
                compute_dfl(before_dfl, dfl_len, box);

                float x1,y1,x2,y2,w,h;
                x1 = (-box[0] + j + 0.5)*stride;
                y1 = (-box[1] + i + 0.5)*stride;
                x2 = (box[2] + j + 0.5)*stride;
                y2 = (box[3] + i + 0.5)*stride;
                w = x2 - x1;
                h = y2 - y1;
                boxes.push_back(x1);
                boxes.push_back(y1);
                boxes.push_back(w);
                boxes.push_back(h);

                objProbs.push_back(max_score);
                classId.push_back(max_class_id);
                validCount ++;
            }
        }
    }
    return validCount;
}


#if defined(RV1106_1103)
static int process_i8_rv1106(int8_t *box_tensor, int32_t box_zp, float box_scale,
                             int8_t *score_tensor, int32_t score_zp, float score_scale,
                             int8_t *score_sum_tensor, int32_t score_sum_zp, float score_sum_scale,
                             int grid_h, int grid_w, int stride, int dfl_len,
                             std::vector<float> &boxes,
                             std::vector<float> &objProbs,
                             std::vector<int> &classId,
                             float threshold) {
    int validCount = 0;
    int grid_len = grid_h * grid_w;
    int8_t score_thres_i8 = qnt_f32_to_affine(threshold, score_zp, score_scale);
    int8_t score_sum_thres_i8 = qnt_f32_to_affine(threshold, score_sum_zp, score_sum_scale);

    for (int i = 0; i < grid_h; i++) {
        for (int j = 0; j < grid_w; j++) {
            int offset = i * grid_w + j;
            int max_class_id = -1;

            // 通过 score sum 起到快速过滤的作用
            if (score_sum_tensor != nullptr) {
                //score_sum_tensor [1, 1, 80, 80]
                if (score_sum_tensor[offset] < score_sum_thres_i8) {
                    continue;
                }
            }

            int8_t max_score = -score_zp;
            offset = offset * OBJ_CLASS_NUM;
            for (int c = 0; c < OBJ_CLASS_NUM; c++) {
                if ((score_tensor[offset + c] > score_thres_i8) && (score_tensor[offset + c] > max_score)) {
                    max_score = score_tensor[offset + c]; //80类 [1, 80, 80, 80] 3588NCHW 1106NHWC
                    max_class_id = c;
                }
            }

            // compute box
            if (max_score > score_thres_i8) {
                offset = (i * grid_w + j) * 4 * dfl_len;
                float box[4];
                float before_dfl[dfl_len*4];
                for (int k=0; k< dfl_len*4; k++){
                    before_dfl[k] = deqnt_affine_to_f32(box_tensor[offset + k], box_zp, box_scale);
                }
                compute_dfl(before_dfl, dfl_len, box);

                float x1, y1, x2, y2, w, h;
                x1 = (-box[0] + j + 0.5) * stride;
                y1 = (-box[1] + i + 0.5) * stride;
                x2 = (box[2] + j + 0.5) * stride;
                y2 = (box[3] + i + 0.5) * stride;
                w = x2 - x1;
                h = y2 - y1;
                boxes.push_back(x1);
                boxes.push_back(y1);
                boxes.push_back(w);
                boxes.push_back(h);

                objProbs.push_back(deqnt_affine_to_f32(max_score, score_zp, score_scale));
                classId.push_back(max_class_id);
                validCount ++;
            }
        }
    }
    printf("validCount=%d\n", validCount);
    printf("grid h-%d, w-%d, stride %d\n", grid_h, grid_w, stride);
    return validCount;
}
#endif

static int yolov8_output_offset(int channel, int anchor, int channels, int anchors, bool channel_first)
{
    return channel_first ? channel * anchors + anchor : anchor * channels + channel;
}

static float yolov8_tensor_value(float *tensor, int offset, int32_t zp, float scale)
{
    (void)zp;
    (void)scale;
    return tensor[offset];
}

static float yolov8_tensor_value(int8_t *tensor, int offset, int32_t zp, float scale)
{
    return deqnt_affine_to_f32(tensor[offset], zp, scale);
}

static float yolov8_tensor_value(uint8_t *tensor, int offset, int32_t zp, float scale)
{
    return deqnt_affine_u8_to_f32(tensor[offset], zp, scale);
}

static bool yolov8_parse_shape(rknn_tensor_attr *attr, int expected_channels,
                               int *channels, int *anchors, bool *channel_first)
{
    if (attr->n_dims >= 3 && attr->dims[1] == expected_channels)
    {
        *channels = attr->dims[1];
        *anchors = attr->dims[2];
        *channel_first = true;
        return true;
    }
    if (attr->n_dims >= 3 && attr->dims[2] == expected_channels)
    {
        *channels = attr->dims[2];
        *anchors = attr->dims[1];
        *channel_first = false;
        return true;
    }
    return false;
}

static float yolov8_tensor_value_by_attr(void *tensor, rknn_tensor_attr *attr, int offset)
{
    if (attr->type == RKNN_TENSOR_INT8)
    {
        return deqnt_affine_to_f32(((int8_t *)tensor)[offset], attr->zp, attr->scale);
    }
    if (attr->type == RKNN_TENSOR_UINT8)
    {
        return deqnt_affine_u8_to_f32(((uint8_t *)tensor)[offset], attr->zp, attr->scale);
    }
    return ((float *)tensor)[offset];
}

static float clamp_float(float value, float min_value, float max_value)
{
    return value < min_value ? min_value : (value > max_value ? max_value : value);
}

static int clamp_int_value(int value, int min_value, int max_value)
{
    return value < min_value ? min_value : (value > max_value ? max_value : value);
}

struct Yolov8SegProtoLayout
{
    int mask_dim;
    int height;
    int width;
    bool channel_first;
};

struct Yolov8SegCandidate
{
    float x;
    float y;
    float w;
    float h;
    float score;
    int class_id;
    std::vector<float> coeffs;
};

struct Yolov8ObbCandidate
{
    float cx;
    float cy;
    float w;
    float h;
    float angle;
    float score;
    int class_id;
};

struct SegBoundaryPoint
{
    float x;
    float y;
    float angle;
};

struct SegBoundaryEdge
{
    int x1;
    int y1;
    int x2;
    int y2;
    bool used;
};

static bool tensor_name_contains(rknn_tensor_attr *attr, const char *needle)
{
    return attr != nullptr && needle != nullptr && strstr(attr->name, needle) != nullptr;
}

static bool yolov8_parse_rank3_shape(rknn_tensor_attr *attr, int *channels, int *anchors, bool *channel_first)
{
    if (attr->n_dims < 3 || attr->dims[1] <= 0 || attr->dims[2] <= 0)
    {
        return false;
    }

    const int dim1 = attr->dims[1];
    const int dim2 = attr->dims[2];
    if (dim1 <= 512 && dim2 > dim1)
    {
        *channels = dim1;
        *anchors = dim2;
        *channel_first = true;
        return true;
    }
    if (dim2 <= 512)
    {
        *channels = dim2;
        *anchors = dim1;
        *channel_first = false;
        return true;
    }

    *channels = dim1;
    *anchors = dim2;
    *channel_first = true;
    return true;
}

static bool yolov8_parse_proto_shape(rknn_tensor_attr *attr, Yolov8SegProtoLayout *layout)
{
    if (attr == nullptr || layout == nullptr || attr->n_dims < 4)
    {
        return false;
    }

    const int dim1 = attr->dims[1];
    const int dim2 = attr->dims[2];
    const int dim3 = attr->dims[3];
    const bool nchw_like = dim1 > 0 && dim1 <= 128 && dim2 >= 4 && dim3 >= 4 && dim2 * dim3 > dim1;
    const bool nhwc_like = dim3 > 0 && dim3 <= 128 && dim1 >= 4 && dim2 >= 4 && dim1 * dim2 > dim3;

    if (nchw_like && (!nhwc_like || dim1 <= dim3))
    {
        layout->mask_dim = dim1;
        layout->height = dim2;
        layout->width = dim3;
        layout->channel_first = true;
        return true;
    }
    if (nhwc_like)
    {
        layout->mask_dim = dim3;
        layout->height = dim1;
        layout->width = dim2;
        layout->channel_first = false;
        return true;
    }
    return false;
}

static bool seg_proto_matches_output_set(rknn_app_context_t *app_ctx,
                                         int candidate_index,
                                         const Yolov8SegProtoLayout &candidate_layout)
{
    if (app_ctx->io_num.n_output == 2)
    {
        const int pred_index = candidate_index == 0 ? 1 : 0;
        rknn_tensor_attr *pred_attr = &app_ctx->output_attrs[pred_index];
        return pred_attr->n_dims >= 3 &&
               ((pred_attr->dims[1] > 4 + candidate_layout.mask_dim) ||
                (pred_attr->dims[2] > 4 + candidate_layout.mask_dim));
    }

    if (app_ctx->io_num.n_output >= 4)
    {
        bool has_boxes = false;
        bool has_coeffs = false;
        for (int j = 0; j < app_ctx->io_num.n_output; ++j)
        {
            if (j == candidate_index)
            {
                continue;
            }
            int channels = 0;
            int anchors = 0;
            bool channel_first = true;
            if (yolov8_parse_shape(&app_ctx->output_attrs[j], 4, &channels, &anchors, &channel_first))
            {
                has_boxes = true;
                continue;
            }
            if (yolov8_parse_shape(&app_ctx->output_attrs[j], candidate_layout.mask_dim,
                                   &channels, &anchors, &channel_first))
            {
                has_coeffs = true;
            }
        }
        return has_boxes && has_coeffs;
    }

    return false;
}

static bool find_seg_proto_output(rknn_app_context_t *app_ctx, int *proto_index, Yolov8SegProtoLayout *proto_layout)
{
    if (app_ctx == nullptr || proto_index == nullptr || proto_layout == nullptr)
    {
        return false;
    }

    int fallback_index = -1;
    Yolov8SegProtoLayout fallback_layout;
    memset(&fallback_layout, 0, sizeof(fallback_layout));

    for (int i = 0; i < app_ctx->io_num.n_output; ++i)
    {
        Yolov8SegProtoLayout candidate_layout;
        if (!yolov8_parse_proto_shape(&app_ctx->output_attrs[i], &candidate_layout))
        {
            continue;
        }
        if (!seg_proto_matches_output_set(app_ctx, i, candidate_layout))
        {
            continue;
        }

        if (tensor_name_contains(&app_ctx->output_attrs[i], "proto"))
        {
            *proto_index = i;
            *proto_layout = candidate_layout;
            return true;
        }
        if (fallback_index < 0)
        {
            fallback_index = i;
            fallback_layout = candidate_layout;
        }
    }

    if (fallback_index >= 0)
    {
        *proto_index = fallback_index;
        *proto_layout = fallback_layout;
        return true;
    }
    return false;
}

static int infer_seg_class_count(rknn_tensor_attr *det_attr, int mask_dim, int fallback_class_count)
{
    int channels = 0;
    int anchors = 0;
    bool channel_first = true;
    (void)anchors;
    (void)channel_first;
    if (det_attr != nullptr && det_attr->n_dims >= 3 && det_attr->dims[1] > 4 + mask_dim)
    {
        channels = det_attr->dims[1];
    }
    else if (det_attr != nullptr && det_attr->n_dims >= 3 && det_attr->dims[2] > 4 + mask_dim)
    {
        channels = det_attr->dims[2];
    }
    if (channels > 4 + mask_dim)
    {
        return channels - 4 - mask_dim;
    }
    return fallback_class_count > 0 ? fallback_class_count : OBJ_CLASS_NUM;
}

template <typename T>
static int process_yolov8_one_output(T *tensor, int32_t zp, float scale,
                                     int channels, int anchors, bool channel_first, int class_count,
                                     std::vector<float> &boxes,
                                     std::vector<float> &objProbs,
                                     std::vector<int> &classId,
                                     float threshold)
{
    int validCount = 0;
    for (int anchor = 0; anchor < anchors; ++anchor)
    {
        int max_class_id = -1;
        float max_score = 0.0f;
        for (int c = 0; c < class_count; ++c)
        {
            int offset = yolov8_output_offset(4 + c, anchor, channels, anchors, channel_first);
            float score = yolov8_tensor_value(tensor, offset, zp, scale);
            if (score > max_score)
            {
                max_score = score;
                max_class_id = c;
            }
        }

        if (max_class_id < 0 || max_score <= threshold)
        {
            continue;
        }

        float cx = yolov8_tensor_value(tensor, yolov8_output_offset(0, anchor, channels, anchors, channel_first), zp, scale);
        float cy = yolov8_tensor_value(tensor, yolov8_output_offset(1, anchor, channels, anchors, channel_first), zp, scale);
        float w = yolov8_tensor_value(tensor, yolov8_output_offset(2, anchor, channels, anchors, channel_first), zp, scale);
        float h = yolov8_tensor_value(tensor, yolov8_output_offset(3, anchor, channels, anchors, channel_first), zp, scale);
        if (!isfinite(cx) || !isfinite(cy) || !isfinite(w) || !isfinite(h) || w <= 0.0f || h <= 0.0f)
        {
            continue;
        }

        float x1 = cx - w * 0.5f;
        float y1 = cy - h * 0.5f;
        boxes.push_back(x1);
        boxes.push_back(y1);
        boxes.push_back(w);
        boxes.push_back(h);
        objProbs.push_back(max_score > 1.0f ? 1.0f : max_score);
        classId.push_back(max_class_id);
        validCount++;
    }
    return validCount;
}

static int process_yolov8_split_outputs(void *box_tensor, rknn_tensor_attr *box_attr,
                                        int box_channels, int anchors, bool box_channel_first,
                                        void *score_tensor, rknn_tensor_attr *score_attr,
                                        int score_channels, bool score_channel_first, int class_count,
                                        std::vector<float> &boxes,
                                        std::vector<float> &objProbs,
                                        std::vector<int> &classId,
                                        float threshold)
{
    int validCount = 0;
    for (int anchor = 0; anchor < anchors; ++anchor)
    {
        int max_class_id = -1;
        float max_score = 0.0f;
        for (int c = 0; c < class_count; ++c)
        {
            int offset = yolov8_output_offset(c, anchor, score_channels, anchors, score_channel_first);
            float score = yolov8_tensor_value_by_attr(score_tensor, score_attr, offset);
            if (score > max_score)
            {
                max_score = score;
                max_class_id = c;
            }
        }

        if (max_class_id < 0 || max_score <= threshold)
        {
            continue;
        }

        float cx = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                               yolov8_output_offset(0, anchor, box_channels, anchors, box_channel_first));
        float cy = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                               yolov8_output_offset(1, anchor, box_channels, anchors, box_channel_first));
        float w = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                              yolov8_output_offset(2, anchor, box_channels, anchors, box_channel_first));
        float h = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                              yolov8_output_offset(3, anchor, box_channels, anchors, box_channel_first));
        if (!isfinite(cx) || !isfinite(cy) || !isfinite(w) || !isfinite(h) || w <= 0.0f || h <= 0.0f)
        {
            continue;
        }

        boxes.push_back(cx - w * 0.5f);
        boxes.push_back(cy - h * 0.5f);
        boxes.push_back(w);
        boxes.push_back(h);
        objProbs.push_back(max_score > 1.0f ? 1.0f : max_score);
        classId.push_back(max_class_id);
        validCount++;
    }
    return validCount;
}

static void obb_to_points(float cx, float cy, float w, float h, float angle, object_obb_point points[4])
{
    const float half_w = w * 0.5f;
    const float half_h = h * 0.5f;
    const float cos_a = cosf(angle);
    const float sin_a = sinf(angle);
    const float corners[4][2] = {
        {-half_w, -half_h},
        {half_w, -half_h},
        {half_w, half_h},
        {-half_w, half_h},
    };
    for (int i = 0; i < 4; ++i)
    {
        const float x = corners[i][0];
        const float y = corners[i][1];
        points[i].x = cx + x * cos_a - y * sin_a;
        points[i].y = cy + x * sin_a + y * cos_a;
    }
}

static image_rect_t obb_points_to_aabb(const object_obb_point points[4], int width, int height)
{
    float min_x = points[0].x;
    float max_x = points[0].x;
    float min_y = points[0].y;
    float max_y = points[0].y;
    for (int i = 1; i < 4; ++i)
    {
        min_x = std::min(min_x, points[i].x);
        max_x = std::max(max_x, points[i].x);
        min_y = std::min(min_y, points[i].y);
        max_y = std::max(max_y, points[i].y);
    }
    image_rect_t box;
    box.left = clamp_int_value((int)floorf(min_x), 0, width);
    box.top = clamp_int_value((int)floorf(min_y), 0, height);
    box.right = clamp_int_value((int)ceilf(max_x), 0, width);
    box.bottom = clamp_int_value((int)ceilf(max_y), 0, height);
    if (box.right <= box.left)
    {
        box.right = clamp_int_value(box.left + 1, 0, width);
    }
    if (box.bottom <= box.top)
    {
        box.bottom = clamp_int_value(box.top + 1, 0, height);
    }
    return box;
}

static int process_yolov8_obb_one_output(void *tensor, rknn_tensor_attr *attr,
                                         int channels, int anchors, bool channel_first,
                                         int class_count,
                                         std::vector<Yolov8ObbCandidate> &candidates,
                                         float threshold)
{
    int validCount = 0;
    for (int anchor = 0; anchor < anchors; ++anchor)
    {
        int max_class_id = -1;
        float max_score = 0.0f;
        for (int c = 0; c < class_count; ++c)
        {
            const int offset = yolov8_output_offset(4 + c, anchor, channels, anchors, channel_first);
            const float score = yolov8_tensor_value_by_attr(tensor, attr, offset);
            if (score > max_score)
            {
                max_score = score;
                max_class_id = c;
            }
        }
        if (max_class_id < 0 || max_score <= threshold)
        {
            continue;
        }

        Yolov8ObbCandidate candidate;
        candidate.cx = yolov8_tensor_value_by_attr(tensor, attr, yolov8_output_offset(0, anchor, channels, anchors, channel_first));
        candidate.cy = yolov8_tensor_value_by_attr(tensor, attr, yolov8_output_offset(1, anchor, channels, anchors, channel_first));
        candidate.w = yolov8_tensor_value_by_attr(tensor, attr, yolov8_output_offset(2, anchor, channels, anchors, channel_first));
        candidate.h = yolov8_tensor_value_by_attr(tensor, attr, yolov8_output_offset(3, anchor, channels, anchors, channel_first));
        candidate.angle = yolov8_tensor_value_by_attr(tensor, attr, yolov8_output_offset(4 + class_count, anchor, channels, anchors, channel_first));
        candidate.score = max_score > 1.0f ? 1.0f : max_score;
        candidate.class_id = max_class_id;
        if (!isfinite(candidate.cx) || !isfinite(candidate.cy) || !isfinite(candidate.w) ||
            !isfinite(candidate.h) || !isfinite(candidate.angle) ||
            candidate.w <= 0.0f || candidate.h <= 0.0f)
        {
            continue;
        }
        candidates.push_back(candidate);
        validCount++;
    }
    return validCount;
}

static int process_yolov8_obb_split_outputs(void *box_tensor, rknn_tensor_attr *box_attr,
                                            int box_channels, int anchors, bool box_channel_first,
                                            void *angle_tensor, rknn_tensor_attr *angle_attr,
                                            int angle_channels, bool angle_channel_first,
                                            void *score_tensor, rknn_tensor_attr *score_attr,
                                            int score_channels, bool score_channel_first,
                                            int class_count,
                                            std::vector<Yolov8ObbCandidate> &candidates,
                                            float threshold)
{
    if (angle_channels < 1)
    {
        return -1;
    }
    int validCount = 0;
    for (int anchor = 0; anchor < anchors; ++anchor)
    {
        int max_class_id = -1;
        float max_score = 0.0f;
        for (int c = 0; c < class_count; ++c)
        {
            const int offset = yolov8_output_offset(c, anchor, score_channels, anchors, score_channel_first);
            const float score = yolov8_tensor_value_by_attr(score_tensor, score_attr, offset);
            if (score > max_score)
            {
                max_score = score;
                max_class_id = c;
            }
        }
        if (max_class_id < 0 || max_score <= threshold)
        {
            continue;
        }

        Yolov8ObbCandidate candidate;
        candidate.cx = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                   yolov8_output_offset(0, anchor, box_channels, anchors, box_channel_first));
        candidate.cy = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                   yolov8_output_offset(1, anchor, box_channels, anchors, box_channel_first));
        candidate.w = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                  yolov8_output_offset(2, anchor, box_channels, anchors, box_channel_first));
        candidate.h = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                  yolov8_output_offset(3, anchor, box_channels, anchors, box_channel_first));
        candidate.angle = yolov8_tensor_value_by_attr(angle_tensor, angle_attr,
                                                      yolov8_output_offset(0, anchor, angle_channels, anchors, angle_channel_first));
        candidate.score = max_score > 1.0f ? 1.0f : max_score;
        candidate.class_id = max_class_id;
        if (!isfinite(candidate.cx) || !isfinite(candidate.cy) || !isfinite(candidate.w) ||
            !isfinite(candidate.h) || !isfinite(candidate.angle) ||
            candidate.w <= 0.0f || candidate.h <= 0.0f)
        {
            continue;
        }
        candidates.push_back(candidate);
        validCount++;
    }
    return validCount;
}

static int process_yolov8_combined_seg_output(void *pred_tensor, rknn_tensor_attr *pred_attr,
                                              int mask_dim, float threshold,
                                              std::vector<Yolov8SegCandidate> &candidates)
{
    int channels = 0;
    int anchors = 0;
    bool channel_first = true;

    if (pred_attr == nullptr || pred_attr->n_dims < 3)
    {
        return -1;
    }
    if (pred_attr->dims[1] > 4 + mask_dim)
    {
        channels = pred_attr->dims[1];
        anchors = pred_attr->dims[2];
        channel_first = true;
    }
    else if (pred_attr->dims[2] > 4 + mask_dim)
    {
        channels = pred_attr->dims[2];
        anchors = pred_attr->dims[1];
        channel_first = false;
    }
    else
    {
        return -1;
    }

    const int class_count = channels - 4 - mask_dim;
    if (class_count <= 0 || anchors <= 0)
    {
        return -1;
    }

    int validCount = 0;
    for (int anchor = 0; anchor < anchors; ++anchor)
    {
        int max_class_id = -1;
        float max_score = 0.0f;
        for (int c = 0; c < class_count; ++c)
        {
            const int offset = yolov8_output_offset(4 + c, anchor, channels, anchors, channel_first);
            const float score = yolov8_tensor_value_by_attr(pred_tensor, pred_attr, offset);
            if (score > max_score)
            {
                max_score = score;
                max_class_id = c;
            }
        }
        if (max_class_id < 0 || max_score <= threshold)
        {
            continue;
        }

        const float cx = yolov8_tensor_value_by_attr(pred_tensor, pred_attr,
                                                     yolov8_output_offset(0, anchor, channels, anchors, channel_first));
        const float cy = yolov8_tensor_value_by_attr(pred_tensor, pred_attr,
                                                     yolov8_output_offset(1, anchor, channels, anchors, channel_first));
        const float w = yolov8_tensor_value_by_attr(pred_tensor, pred_attr,
                                                    yolov8_output_offset(2, anchor, channels, anchors, channel_first));
        const float h = yolov8_tensor_value_by_attr(pred_tensor, pred_attr,
                                                    yolov8_output_offset(3, anchor, channels, anchors, channel_first));
        if (!isfinite(cx) || !isfinite(cy) || !isfinite(w) || !isfinite(h) || w <= 0.0f || h <= 0.0f)
        {
            continue;
        }

        Yolov8SegCandidate candidate;
        candidate.x = cx - w * 0.5f;
        candidate.y = cy - h * 0.5f;
        candidate.w = w;
        candidate.h = h;
        candidate.score = max_score > 1.0f ? 1.0f : max_score;
        candidate.class_id = max_class_id;
        candidate.coeffs.resize(mask_dim);
        for (int k = 0; k < mask_dim; ++k)
        {
            const int offset = yolov8_output_offset(4 + class_count + k, anchor, channels, anchors, channel_first);
            candidate.coeffs[k] = yolov8_tensor_value_by_attr(pred_tensor, pred_attr, offset);
        }
        candidates.push_back(candidate);
        validCount++;
    }
    return validCount;
}

static int process_yolov8_split_seg_outputs(void *box_tensor, rknn_tensor_attr *box_attr,
                                            int box_channels, int anchors, bool box_channel_first,
                                            void *score_tensor, rknn_tensor_attr *score_attr,
                                            int score_channels, bool score_channel_first,
                                            void *coeff_tensor, rknn_tensor_attr *coeff_attr,
                                            int coeff_channels, bool coeff_channel_first,
                                            float threshold,
                                            std::vector<Yolov8SegCandidate> &candidates)
{
    int validCount = 0;
    for (int anchor = 0; anchor < anchors; ++anchor)
    {
        int max_class_id = -1;
        float max_score = 0.0f;
        for (int c = 0; c < score_channels; ++c)
        {
            const int offset = yolov8_output_offset(c, anchor, score_channels, anchors, score_channel_first);
            const float score = yolov8_tensor_value_by_attr(score_tensor, score_attr, offset);
            if (score > max_score)
            {
                max_score = score;
                max_class_id = c;
            }
        }
        if (max_class_id < 0 || max_score <= threshold)
        {
            continue;
        }

        const float cx = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                     yolov8_output_offset(0, anchor, box_channels, anchors, box_channel_first));
        const float cy = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                     yolov8_output_offset(1, anchor, box_channels, anchors, box_channel_first));
        const float w = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                    yolov8_output_offset(2, anchor, box_channels, anchors, box_channel_first));
        const float h = yolov8_tensor_value_by_attr(box_tensor, box_attr,
                                                    yolov8_output_offset(3, anchor, box_channels, anchors, box_channel_first));
        if (!isfinite(cx) || !isfinite(cy) || !isfinite(w) || !isfinite(h) || w <= 0.0f || h <= 0.0f)
        {
            continue;
        }

        Yolov8SegCandidate candidate;
        candidate.x = cx - w * 0.5f;
        candidate.y = cy - h * 0.5f;
        candidate.w = w;
        candidate.h = h;
        candidate.score = max_score > 1.0f ? 1.0f : max_score;
        candidate.class_id = max_class_id;
        candidate.coeffs.resize(coeff_channels);
        for (int k = 0; k < coeff_channels; ++k)
        {
            const int offset = yolov8_output_offset(k, anchor, coeff_channels, anchors, coeff_channel_first);
            candidate.coeffs[k] = yolov8_tensor_value_by_attr(coeff_tensor, coeff_attr, offset);
        }
        candidates.push_back(candidate);
        validCount++;
    }
    return validCount;
}

static int proto_output_offset(const Yolov8SegProtoLayout &layout, int channel, int y, int x)
{
    return layout.channel_first
               ? channel * layout.height * layout.width + y * layout.width + x
               : (y * layout.width + x) * layout.mask_dim + channel;
}

static void fill_detect_result_from_candidate(const Yolov8SegCandidate &candidate,
                                              letterbox_t *letter_box,
                                              int model_in_w,
                                              int model_in_h,
                                              object_detect_result *det)
{
    const float x1 = candidate.x - letter_box->x_pad;
    const float y1 = candidate.y - letter_box->y_pad;
    const float x2 = x1 + candidate.w;
    const float y2 = y1 + candidate.h;

    det->box.left = (int)(clamp(x1, 0, model_in_w) / letter_box->scale);
    det->box.top = (int)(clamp(y1, 0, model_in_h) / letter_box->scale);
    det->box.right = (int)(clamp(x2, 0, model_in_w) / letter_box->scale);
    det->box.bottom = (int)(clamp(y2, 0, model_in_h) / letter_box->scale);
    det->prop = candidate.score;
    det->cls_id = candidate.class_id;
}

static int select_seg_candidates_after_nms(const std::vector<Yolov8SegCandidate> &candidates,
                                           letterbox_t *letter_box,
                                           float nms_threshold,
                                           int model_in_w,
                                           int model_in_h,
                                           object_detect_result_list *bbox_fallback,
                                           std::vector<int> *selected_indices)
{
    bbox_fallback->count = 0;
    selected_indices->clear();
    const int validCount = (int)candidates.size();
    if (validCount <= 0)
    {
        return 0;
    }

    std::vector<float> boxes;
    std::vector<float> sortScores;
    std::vector<int> classId;
    std::vector<int> indexArray;
    boxes.reserve(validCount * 4);
    sortScores.reserve(validCount);
    classId.reserve(validCount);
    indexArray.reserve(validCount);
    for (int i = 0; i < validCount; ++i)
    {
        boxes.push_back(candidates[i].x);
        boxes.push_back(candidates[i].y);
        boxes.push_back(candidates[i].w);
        boxes.push_back(candidates[i].h);
        sortScores.push_back(candidates[i].score);
        classId.push_back(candidates[i].class_id);
        indexArray.push_back(i);
    }

    quick_sort_indice_inverse(sortScores, 0, validCount - 1, indexArray);
    std::set<int> class_set(std::begin(classId), std::end(classId));
    for (auto c : class_set)
    {
        nms(validCount, boxes, classId, indexArray, c, nms_threshold);
    }

    for (int i = 0; i < validCount && bbox_fallback->count < OBJ_NUMB_MAX_SIZE; ++i)
    {
        if (indexArray[i] == -1)
        {
            continue;
        }
        const int n = indexArray[i];
        object_detect_result *det = &bbox_fallback->results[bbox_fallback->count];
        fill_detect_result_from_candidate(candidates[n], letter_box, model_in_w, model_in_h, det);
        selected_indices->push_back(n);
        bbox_fallback->count++;
    }
    return bbox_fallback->count;
}

static bool append_contour_point(object_seg_contour *contour, int x, int y)
{
    if (contour->count >= 64)
    {
        return false;
    }
    if (contour->count > 0)
    {
        const object_seg_point &last = contour->points[contour->count - 1];
        if (last.x == x && last.y == y)
        {
            return true;
        }
    }
    contour->points[contour->count].x = x;
    contour->points[contour->count].y = y;
    contour->count++;
    return true;
}

static bool fill_bbox_contour(object_seg_result *seg)
{
    if (seg == nullptr)
    {
        return false;
    }
    object_seg_contour *contour = &seg->contours[0];
    contour->count = 0;
    append_contour_point(contour, seg->det.box.left, seg->det.box.top);
    append_contour_point(contour, seg->det.box.right, seg->det.box.top);
    append_contour_point(contour, seg->det.box.right, seg->det.box.bottom);
    append_contour_point(contour, seg->det.box.left, seg->det.box.bottom);
    seg->contour_count = contour->count >= 3 ? 1 : 0;
    return seg->contour_count > 0;
}

static bool boundary_point_angle_less(const SegBoundaryPoint &a, const SegBoundaryPoint &b)
{
    return a.angle < b.angle;
}

static int boundary_edge_direction(const SegBoundaryEdge &edge)
{
    if (edge.x2 > edge.x1)
    {
        return 0; // east
    }
    if (edge.y2 > edge.y1)
    {
        return 1; // south
    }
    if (edge.x2 < edge.x1)
    {
        return 2; // west
    }
    return 3; // north
}

static int boundary_turn_rank(int previous_dir, int next_dir)
{
    const int delta = (next_dir - previous_dir + 4) % 4;
    if (delta == 1)
    {
        return 0; // right turn keeps the foreground on the same side.
    }
    if (delta == 0)
    {
        return 1;
    }
    if (delta == 3)
    {
        return 2;
    }
    return 3;
}

static bool build_mask_contour_from_proto(const Yolov8SegCandidate &candidate,
                                          void *proto_tensor,
                                          rknn_tensor_attr *proto_attr,
                                          const Yolov8SegProtoLayout &proto_layout,
                                          letterbox_t *letter_box,
                                          int model_in_w,
                                          int model_in_h,
                                          object_seg_result *seg)
{
    if (proto_tensor == nullptr || proto_attr == nullptr || letter_box == nullptr ||
        seg == nullptr || candidate.coeffs.size() < (size_t)proto_layout.mask_dim ||
        letter_box->scale <= 0.0f || proto_layout.width <= 0 || proto_layout.height <= 0)
    {
        return false;
    }

    const float model_x1 = clamp_float(candidate.x, 0.0f, (float)model_in_w);
    const float model_y1 = clamp_float(candidate.y, 0.0f, (float)model_in_h);
    const float model_x2 = clamp_float(candidate.x + candidate.w, 0.0f, (float)model_in_w);
    const float model_y2 = clamp_float(candidate.y + candidate.h, 0.0f, (float)model_in_h);
    if (model_x2 <= model_x1 || model_y2 <= model_y1)
    {
        return false;
    }

    const int crop_x0 = clamp_int_value((int)floorf(model_x1 * proto_layout.width / model_in_w), 0, proto_layout.width - 1);
    const int crop_y0 = clamp_int_value((int)floorf(model_y1 * proto_layout.height / model_in_h), 0, proto_layout.height - 1);
    const int crop_x1 = clamp_int_value((int)ceilf(model_x2 * proto_layout.width / model_in_w) - 1, 0, proto_layout.width - 1);
    const int crop_y1 = clamp_int_value((int)ceilf(model_y2 * proto_layout.height / model_in_h) - 1, 0, proto_layout.height - 1);
    const int crop_w = crop_x1 - crop_x0 + 1;
    const int crop_h = crop_y1 - crop_y0 + 1;
    if (crop_w <= 0 || crop_h <= 0)
    {
        return false;
    }

    std::vector<unsigned char> mask(crop_w * crop_h, 0);
    int mask_count = 0;
    for (int py = crop_y0; py <= crop_y1; ++py)
    {
        for (int px = crop_x0; px <= crop_x1; ++px)
        {
            float logit = 0.0f;
            for (int k = 0; k < proto_layout.mask_dim; ++k)
            {
                const int offset = proto_output_offset(proto_layout, k, py, px);
                logit += candidate.coeffs[k] * yolov8_tensor_value_by_attr(proto_tensor, proto_attr, offset);
            }
            if (sigmoid(logit) >= 0.5f)
            {
                mask[(py - crop_y0) * crop_w + (px - crop_x0)] = 1;
                mask_count++;
            }
        }
    }
    if (mask_count < 3)
    {
        return false;
    }

    const int src_w = std::max(1, (int)((model_in_w - 2 * letter_box->x_pad) / letter_box->scale + 0.5f));
    const int src_h = std::max(1, (int)((model_in_h - 2 * letter_box->y_pad) / letter_box->scale + 0.5f));
    const int max_x = src_w - 1;
    const int max_y = src_h - 1;

    std::vector<SegBoundaryEdge> edges;
    edges.reserve(mask_count * 2);
    for (int y = 0; y < crop_h; ++y)
    {
        for (int x = 0; x < crop_w; ++x)
        {
            if (!mask[y * crop_w + x])
            {
                continue;
            }
            if (y == 0 || !mask[(y - 1) * crop_w + x])
            {
                edges.push_back({x, y, x + 1, y, false});
            }
            if (x == crop_w - 1 || !mask[y * crop_w + x + 1])
            {
                edges.push_back({x + 1, y, x + 1, y + 1, false});
            }
            if (y == crop_h - 1 || !mask[(y + 1) * crop_w + x])
            {
                edges.push_back({x + 1, y + 1, x, y + 1, false});
            }
            if (x == 0 || !mask[y * crop_w + x - 1])
            {
                edges.push_back({x, y + 1, x, y, false});
            }
        }
    }
    if (edges.size() < 3)
    {
        return false;
    }

    std::vector<SegBoundaryPoint> best_loop;
    for (size_t start = 0; start < edges.size(); ++start)
    {
        if (edges[start].used)
        {
            continue;
        }
        std::vector<SegBoundaryPoint> loop;
        loop.reserve(128);
        edges[start].used = true;
        const int first_x = edges[start].x1;
        const int first_y = edges[start].y1;
        int current_x = edges[start].x2;
        int current_y = edges[start].y2;
        loop.push_back({(float)first_x, (float)first_y, 0.0f});
        loop.push_back({(float)current_x, (float)current_y, 0.0f});
        int previous_dir = boundary_edge_direction(edges[start]);
        bool closed_loop = false;

        for (size_t guard = 0; guard < edges.size(); ++guard)
        {
            if (current_x == first_x && current_y == first_y)
            {
                closed_loop = true;
                break;
            }
            int next_index = -1;
            int next_rank = 100;
            for (size_t i = 0; i < edges.size(); ++i)
            {
                if (!edges[i].used && edges[i].x1 == current_x && edges[i].y1 == current_y)
                {
                    const int rank = boundary_turn_rank(previous_dir, boundary_edge_direction(edges[i]));
                    if (rank < next_rank)
                    {
                        next_rank = rank;
                        next_index = (int)i;
                    }
                }
            }
            if (next_index < 0)
            {
                break;
            }
            edges[(size_t)next_index].used = true;
            previous_dir = boundary_edge_direction(edges[(size_t)next_index]);
            current_x = edges[(size_t)next_index].x2;
            current_y = edges[(size_t)next_index].y2;
            loop.push_back({(float)current_x, (float)current_y, 0.0f});
        }

        if (!closed_loop)
        {
            continue;
        }
        if (loop.size() > 1)
        {
            const SegBoundaryPoint &first = loop.front();
            const SegBoundaryPoint &last = loop.back();
            if ((int)first.x == (int)last.x && (int)first.y == (int)last.y)
            {
                loop.pop_back();
            }
        }
        if (loop.size() > best_loop.size())
        {
            best_loop.swap(loop);
        }
    }
    if (best_loop.size() < 3)
    {
        return false;
    }

    object_seg_contour *contour = &seg->contours[0];
    contour->count = 0;
    const int target_count = (int)std::min((size_t)64, best_loop.size());
    for (int i = 0; i < target_count; ++i)
    {
        const size_t source_index = (size_t)i * best_loop.size() / target_count;
        const float proto_x = (float)crop_x0 + best_loop[source_index].x;
        const float proto_y = (float)crop_y0 + best_loop[source_index].y;
        const float model_x = proto_x * model_in_w / proto_layout.width;
        const float model_y = proto_y * model_in_h / proto_layout.height;
        const float image_x = (model_x - letter_box->x_pad) / letter_box->scale;
        const float image_y = (model_y - letter_box->y_pad) / letter_box->scale;
        const int x = clamp_int_value((int)(clamp_float(image_x, 0.0f, (float)max_x) + 0.5f), 0, max_x);
        const int y = clamp_int_value((int)(clamp_float(image_y, 0.0f, (float)max_y) + 0.5f), 0, max_y);
        append_contour_point(contour, x, y);
    }
    if (contour->count > 1)
    {
        const object_seg_point &first = contour->points[0];
        const object_seg_point &last = contour->points[contour->count - 1];
        if (first.x == last.x && first.y == last.y)
        {
            contour->count--;
        }
    }

    if (contour->count < 3)
    {
        return false;
    }

    seg->has_mask = 1;
    seg->mask_width = proto_layout.width;
    seg->mask_height = proto_layout.height;
    seg->contour_count = 1;
    return true;
}

static int fill_detect_results_from_vectors(int validCount,
                                            std::vector<float> &filterBoxes,
                                            std::vector<float> &objProbs,
                                            std::vector<int> &classId,
                                            letterbox_t *letter_box,
                                            float nms_threshold,
                                            int model_in_w,
                                            int model_in_h,
                                            object_detect_result_list *od_results)
{
    if (validCount <= 0)
    {
        return 0;
    }
    std::vector<int> indexArray;
    for (int i = 0; i < validCount; ++i)
    {
        indexArray.push_back(i);
    }
    quick_sort_indice_inverse(objProbs, 0, validCount - 1, indexArray);

    std::set<int> class_set(std::begin(classId), std::end(classId));
    for (auto c : class_set)
    {
        nms(validCount, filterBoxes, classId, indexArray, c, nms_threshold);
    }

    int last_count = 0;
    od_results->count = 0;
    for (int i = 0; i < validCount; ++i)
    {
        if (indexArray[i] == -1 || last_count >= OBJ_NUMB_MAX_SIZE)
        {
            continue;
        }
        int n = indexArray[i];

        float x1 = filterBoxes[n * 4 + 0] - letter_box->x_pad;
        float y1 = filterBoxes[n * 4 + 1] - letter_box->y_pad;
        float x2 = x1 + filterBoxes[n * 4 + 2];
        float y2 = y1 + filterBoxes[n * 4 + 3];
        int id = classId[n];
        float obj_conf = objProbs[i];

        od_results->results[last_count].box.left = (int)(clamp(x1, 0, model_in_w) / letter_box->scale);
        od_results->results[last_count].box.top = (int)(clamp(y1, 0, model_in_h) / letter_box->scale);
        od_results->results[last_count].box.right = (int)(clamp(x2, 0, model_in_w) / letter_box->scale);
        od_results->results[last_count].box.bottom = (int)(clamp(y2, 0, model_in_h) / letter_box->scale);
        od_results->results[last_count].prop = obj_conf;
        od_results->results[last_count].cls_id = id;
        last_count++;
    }
    od_results->count = last_count;
    return 0;
}

int post_process(rknn_app_context_t *app_ctx, void *outputs, letterbox_t *letter_box, float conf_threshold, float nms_threshold, object_detect_result_list *od_results)
{
#if defined(RV1106_1103) 
    rknn_tensor_mem **_outputs = (rknn_tensor_mem **)outputs;
#else
    rknn_output *_outputs = (rknn_output *)outputs;
#endif
    std::vector<float> filterBoxes;
    std::vector<float> objProbs;
    std::vector<int> classId;
    int validCount = 0;
    int stride = 0;
    int grid_h = 0;
    int grid_w = 0;
    int model_in_w = app_ctx->model_width;
    int model_in_h = app_ctx->model_height;
    int class_count = app_ctx->class_count > 0 ? app_ctx->class_count : OBJ_CLASS_NUM;

    memset(od_results, 0, sizeof(object_detect_result_list));

    if (app_ctx->io_num.n_output == 1)
    {
        rknn_tensor_attr *attr = &app_ctx->output_attrs[0];
        int channels = 0;
        int anchors = 0;
        bool channel_first = true;

        if (!yolov8_parse_shape(attr, class_count + 4, &channels, &anchors, &channel_first))
        {
            printf("unsupported single-output YOLOv8 shape: n_dims=%d dims=[%d, %d, %d, %d], expected channel count %d\n",
                   attr->n_dims, attr->dims[0], attr->dims[1], attr->dims[2], attr->dims[3],
                   class_count + 4);
            return -1;
        }

#if defined(RV1106_1103)
        printf("single-output YOLOv8 postprocess is not implemented for RV1106/1103 zero-copy path\n");
        return -1;
#else
        if (attr->type == RKNN_TENSOR_INT8)
        {
            validCount += process_yolov8_one_output((int8_t *)_outputs[0].buf, attr->zp, attr->scale,
                                                    channels, anchors, channel_first, class_count,
                                                    filterBoxes, objProbs, classId, conf_threshold);
        }
        else if (attr->type == RKNN_TENSOR_UINT8)
        {
            validCount += process_yolov8_one_output((uint8_t *)_outputs[0].buf, attr->zp, attr->scale,
                                                    channels, anchors, channel_first, class_count,
                                                    filterBoxes, objProbs, classId, conf_threshold);
        }
        else
        {
            validCount += process_yolov8_one_output((float *)_outputs[0].buf, attr->zp, attr->scale,
                                                    channels, anchors, channel_first, class_count,
                                                    filterBoxes, objProbs, classId, conf_threshold);
        }
#endif
    }
    else if (app_ctx->io_num.n_output == 2)
    {
#if defined(RV1106_1103)
        printf("split-output YOLOv8 postprocess is not implemented for RV1106/1103 zero-copy path\n");
        return -1;
#else
        rknn_tensor_attr *box_attr = &app_ctx->output_attrs[0];
        rknn_tensor_attr *score_attr = &app_ctx->output_attrs[1];
        int box_channels = 0;
        int box_anchors = 0;
        int score_channels = 0;
        int score_anchors = 0;
        bool box_channel_first = true;
        bool score_channel_first = true;

        bool box_ok = yolov8_parse_shape(box_attr, 4, &box_channels, &box_anchors, &box_channel_first);
        bool score_ok = yolov8_parse_shape(score_attr, class_count, &score_channels, &score_anchors, &score_channel_first);
        if (!box_ok || !score_ok || box_anchors != score_anchors)
        {
            printf("unsupported split-output YOLOv8 shapes: box n_dims=%d dims=[%d, %d, %d, %d], "
                   "score n_dims=%d dims=[%d, %d, %d, %d], expected box channels 4 and score channels %d\n",
                   box_attr->n_dims, box_attr->dims[0], box_attr->dims[1], box_attr->dims[2], box_attr->dims[3],
                   score_attr->n_dims, score_attr->dims[0], score_attr->dims[1], score_attr->dims[2], score_attr->dims[3],
                   class_count);
            return -1;
        }

        validCount += process_yolov8_split_outputs(_outputs[0].buf, box_attr,
                                                   box_channels, box_anchors, box_channel_first,
                                                   _outputs[1].buf, score_attr,
                                                   score_channels, score_channel_first, class_count,
                                                   filterBoxes, objProbs, classId, conf_threshold);
#endif
    }
    else
    {
    // default 3 branch
#ifdef RKNPU1
    int dfl_len = app_ctx->output_attrs[0].dims[2] / 4;
#else
    int dfl_len = app_ctx->output_attrs[0].dims[1] /4;
#endif
    int output_per_branch = app_ctx->io_num.n_output / 3;
    for (int i = 0; i < 3; i++)
    {
#if defined(RV1106_1103)
        dfl_len = app_ctx->output_attrs[0].dims[3] /4;
        void *score_sum = nullptr;
        int32_t score_sum_zp = 0;
        float score_sum_scale = 1.0;
        if (output_per_branch == 3) {
            score_sum = _outputs[i * output_per_branch + 2]->virt_addr;
            score_sum_zp = app_ctx->output_attrs[i * output_per_branch + 2].zp;
            score_sum_scale = app_ctx->output_attrs[i * output_per_branch + 2].scale;
        }
        int box_idx = i * output_per_branch;
        int score_idx = i * output_per_branch + 1;
        grid_h = app_ctx->output_attrs[box_idx].dims[1];
        grid_w = app_ctx->output_attrs[box_idx].dims[2];
        stride = model_in_h / grid_h;
        
        if (app_ctx->is_quant) {
            validCount += process_i8_rv1106((int8_t *)_outputs[box_idx]->virt_addr, app_ctx->output_attrs[box_idx].zp, app_ctx->output_attrs[box_idx].scale,
                                (int8_t *)_outputs[score_idx]->virt_addr, app_ctx->output_attrs[score_idx].zp,
                                app_ctx->output_attrs[score_idx].scale, (int8_t *)score_sum, score_sum_zp, score_sum_scale,
                                grid_h, grid_w, stride, dfl_len, filterBoxes, objProbs, classId, conf_threshold);
        }
        else
        {
            printf("RV1106/1103 only support quantization mode\n", LABEL_NALE_TXT_PATH);
            return -1;
        }

#else
        void *score_sum = nullptr;
        int32_t score_sum_zp = 0;
        float score_sum_scale = 1.0;
        if (output_per_branch == 3){
            score_sum = _outputs[i*output_per_branch + 2].buf;
            score_sum_zp = app_ctx->output_attrs[i*output_per_branch + 2].zp;
            score_sum_scale = app_ctx->output_attrs[i*output_per_branch + 2].scale;
        }
        int box_idx = i*output_per_branch;
        int score_idx = i*output_per_branch + 1;

#ifdef RKNPU1
        grid_h = app_ctx->output_attrs[box_idx].dims[1];
        grid_w = app_ctx->output_attrs[box_idx].dims[0];
#else
        grid_h = app_ctx->output_attrs[box_idx].dims[2];
        grid_w = app_ctx->output_attrs[box_idx].dims[3];
#endif
        stride = model_in_h / grid_h;

        if (app_ctx->is_quant)
        {
#ifdef RKNPU1
            validCount += process_u8((uint8_t *)_outputs[box_idx].buf, app_ctx->output_attrs[box_idx].zp, app_ctx->output_attrs[box_idx].scale,
                                     (uint8_t *)_outputs[score_idx].buf, app_ctx->output_attrs[score_idx].zp, app_ctx->output_attrs[score_idx].scale,
                                     (uint8_t *)score_sum, score_sum_zp, score_sum_scale,
                                     grid_h, grid_w, stride, dfl_len,
                                     filterBoxes, objProbs, classId, conf_threshold);
#else
            validCount += process_i8((int8_t *)_outputs[box_idx].buf, app_ctx->output_attrs[box_idx].zp, app_ctx->output_attrs[box_idx].scale,
                                     (int8_t *)_outputs[score_idx].buf, app_ctx->output_attrs[score_idx].zp, app_ctx->output_attrs[score_idx].scale,
                                     (int8_t *)score_sum, score_sum_zp, score_sum_scale,
                                     grid_h, grid_w, stride, dfl_len, 
                                     filterBoxes, objProbs, classId, conf_threshold);
#endif
        }
        else
        {
            validCount += process_fp32((float *)_outputs[box_idx].buf, (float *)_outputs[score_idx].buf, (float *)score_sum,
                                       grid_h, grid_w, stride, dfl_len, 
                                       filterBoxes, objProbs, classId, conf_threshold);
        }
#endif
    }
    }

    return fill_detect_results_from_vectors(validCount, filterBoxes, objProbs, classId,
                                            letter_box, nms_threshold, model_in_w, model_in_h,
                                            od_results);
}

int post_process_obb(rknn_app_context_t *app_ctx, void *outputs, letterbox_t *letter_box,
                     float conf_threshold, float nms_threshold,
                     object_obb_result_list *obb_results,
                     object_detect_result_list *bbox_fallback)
{
    if (obb_results == nullptr || bbox_fallback == nullptr)
    {
        return -1;
    }
    memset(obb_results, 0, sizeof(*obb_results));
    memset(bbox_fallback, 0, sizeof(*bbox_fallback));
    if (app_ctx == nullptr || outputs == nullptr || letter_box == nullptr)
    {
        return -1;
    }

#if defined(RV1106_1103)
    printf("YOLOv8-OBB postprocess is not implemented for RV1106/1103 zero-copy path\n");
    return -1;
#else
    rknn_output *_outputs = (rknn_output *)outputs;
    std::vector<Yolov8ObbCandidate> candidates;

    if (app_ctx->io_num.n_output == 1)
    {
        rknn_tensor_attr *attr = &app_ctx->output_attrs[0];
        int channels = 0;
        int anchors = 0;
        bool channel_first = true;
        if (!yolov8_parse_rank3_shape(attr, &channels, &anchors, &channel_first) ||
            channels <= 5 || anchors <= 0)
        {
            printf("unsupported single-output YOLOv8-OBB shape: n_dims=%d dims=[%d, %d, %d, %d]\n",
                   attr->n_dims, attr->dims[0], attr->dims[1], attr->dims[2], attr->dims[3]);
            return -1;
        }
        const int class_count = channels - 5;
        process_yolov8_obb_one_output(_outputs[0].buf, attr, channels, anchors, channel_first,
                                      class_count, candidates, conf_threshold);
    }
    else if (app_ctx->io_num.n_output >= 3)
    {
        int box_index = -1;
        int angle_index = -1;
        int score_index = -1;
        int box_channels = 0;
        int box_anchors = 0;
        int angle_channels = 0;
        int angle_anchors = 0;
        int score_channels = 0;
        int score_anchors = 0;
        bool box_channel_first = true;
        bool angle_channel_first = true;
        bool score_channel_first = true;

        for (int i = 0; i < app_ctx->io_num.n_output; ++i)
        {
            rknn_tensor_attr *attr = &app_ctx->output_attrs[i];
            int channels = 0;
            int anchors = 0;
            bool channel_first = true;
            if (box_index < 0 && yolov8_parse_shape(attr, 4, &channels, &anchors, &channel_first))
            {
                box_index = i;
                box_channels = channels;
                box_anchors = anchors;
                box_channel_first = channel_first;
                continue;
            }
            if (angle_index < 0 && yolov8_parse_shape(attr, 1, &channels, &anchors, &channel_first))
            {
                angle_index = i;
                angle_channels = channels;
                angle_anchors = anchors;
                angle_channel_first = channel_first;
                continue;
            }
        }

        int expected_class_count = app_ctx->class_count > 0 ? app_ctx->class_count : 1;
        if (expected_class_count > 1)
        {
            expected_class_count -= 1; // detect inference sees OBB single-class as channels-4.
        }
        expected_class_count = std::max(1, expected_class_count);
        for (int i = 0; i < app_ctx->io_num.n_output; ++i)
        {
            if (i == box_index || i == angle_index)
            {
                continue;
            }
            rknn_tensor_attr *attr = &app_ctx->output_attrs[i];
            int channels = 0;
            int anchors = 0;
            bool channel_first = true;
            if (yolov8_parse_shape(attr, expected_class_count, &channels, &anchors, &channel_first))
            {
                score_index = i;
                score_channels = channels;
                score_anchors = anchors;
                score_channel_first = channel_first;
                break;
            }
            if (yolov8_parse_rank3_shape(attr, &channels, &anchors, &channel_first) &&
                channels > 0 && channels <= 128)
            {
                score_index = i;
                score_channels = channels;
                score_anchors = anchors;
                score_channel_first = channel_first;
            }
        }

        if (box_index < 0 || angle_index < 0 || score_index < 0 ||
            box_anchors != angle_anchors || box_anchors != score_anchors)
        {
            printf("unsupported split-output YOLOv8-OBB shapes; expected boxes, angle, scores with matching anchors\n");
            return -1;
        }
        process_yolov8_obb_split_outputs(_outputs[box_index].buf, &app_ctx->output_attrs[box_index],
                                         box_channels, box_anchors, box_channel_first,
                                         _outputs[angle_index].buf, &app_ctx->output_attrs[angle_index],
                                         angle_channels, angle_channel_first,
                                         _outputs[score_index].buf, &app_ctx->output_attrs[score_index],
                                         score_channels, score_channel_first, score_channels,
                                         candidates, conf_threshold);
    }
    else
    {
        printf("unsupported YOLOv8-OBB output count=%d\n", app_ctx->io_num.n_output);
        return -1;
    }

    std::vector<object_obb_result> mapped;
    mapped.reserve(candidates.size());
    const int model_in_w = app_ctx->model_width;
    const int model_in_h = app_ctx->model_height;
    const int source_w = std::max(1, (int)lroundf(((float)model_in_w - 2.0f * letter_box->x_pad) / letter_box->scale));
    const int source_h = std::max(1, (int)lroundf(((float)model_in_h - 2.0f * letter_box->y_pad) / letter_box->scale));
    for (size_t i = 0; i < candidates.size(); ++i)
    {
        object_obb_result result;
        memset(&result, 0, sizeof(result));
        const Yolov8ObbCandidate &candidate = candidates[i];
        object_obb_point model_points[4];
        obb_to_points(candidate.cx, candidate.cy, candidate.w, candidate.h, candidate.angle, model_points);
        for (int p = 0; p < 4; ++p)
        {
            const float src_x = (model_points[p].x - letter_box->x_pad) / letter_box->scale;
            const float src_y = (model_points[p].y - letter_box->y_pad) / letter_box->scale;
            result.points[p].x = clamp_float(src_x, 0.0f, (float)source_w);
            result.points[p].y = clamp_float(src_y, 0.0f, (float)source_h);
        }
        result.cx = (candidate.cx - letter_box->x_pad) / letter_box->scale;
        result.cy = (candidate.cy - letter_box->y_pad) / letter_box->scale;
        result.width = candidate.w / letter_box->scale;
        result.height = candidate.h / letter_box->scale;
        result.angle = candidate.angle;
        result.prop = candidate.score;
        result.cls_id = candidate.class_id;
        result.box = obb_points_to_aabb(result.points, source_w, source_h);
        mapped.push_back(result);
    }

    std::vector<int> order;
    order.reserve(mapped.size());
    for (size_t i = 0; i < mapped.size(); ++i)
    {
        order.push_back((int)i);
    }
    std::sort(order.begin(), order.end(), [&mapped](int a, int b) {
        return mapped[a].prop > mapped[b].prop;
    });

    std::vector<char> suppressed(mapped.size(), 0);
    for (size_t oi = 0; oi < order.size(); ++oi)
    {
        const int i = order[oi];
        if (suppressed[i])
        {
            continue;
        }
        for (size_t oj = oi + 1; oj < order.size(); ++oj)
        {
            const int j = order[oj];
            if (suppressed[j] || mapped[i].cls_id != mapped[j].cls_id)
            {
                continue;
            }
            const image_rect_t &a = mapped[i].box;
            const image_rect_t &b = mapped[j].box;
            const float iou = CalculateOverlap((float)a.left, (float)a.top, (float)a.right, (float)a.bottom,
                                               (float)b.left, (float)b.top, (float)b.right, (float)b.bottom);
            if (iou > nms_threshold)
            {
                suppressed[j] = 1;
            }
        }
    }

    int out_count = 0;
    for (size_t oi = 0; oi < order.size() && out_count < OBJ_NUMB_MAX_SIZE; ++oi)
    {
        const int index = order[oi];
        if (suppressed[index])
        {
            continue;
        }
        obb_results->results[out_count] = mapped[index];
        bbox_fallback->results[out_count].box = mapped[index].box;
        bbox_fallback->results[out_count].prop = mapped[index].prop;
        bbox_fallback->results[out_count].cls_id = mapped[index].cls_id;
        out_count++;
    }
    obb_results->count = out_count;
    bbox_fallback->count = out_count;
    return 0;
#endif
}

int post_process_seg(rknn_app_context_t *app_ctx, void *outputs, letterbox_t *letter_box,
                     float conf_threshold, float nms_threshold,
                     object_seg_result_list *seg_results,
                     object_detect_result_list *bbox_fallback)
{
    if (seg_results == nullptr || bbox_fallback == nullptr)
    {
        return -1;
    }

    memset(seg_results, 0, sizeof(*seg_results));
    memset(bbox_fallback, 0, sizeof(*bbox_fallback));
    seg_results->mask_status = 1;

    if (app_ctx == nullptr || outputs == nullptr || letter_box == nullptr)
    {
        return -1;
    }

#if defined(RV1106_1103)
    static bool warned_rv1106 = false;
    if (!warned_rv1106)
    {
        printf("YOLOv8-seg postprocess: RV1106/1103 mask path is not implemented\n");
        warned_rv1106 = true;
    }
    return -1;
#else
    int proto_index = -1;
    Yolov8SegProtoLayout proto_layout;
    memset(&proto_layout, 0, sizeof(proto_layout));
    if (!find_seg_proto_output(app_ctx, &proto_index, &proto_layout))
    {
        static bool warned_missing_proto = false;
        if (!warned_missing_proto)
        {
            printf("YOLOv8-seg postprocess: protos output not found; using bbox fallback\n");
            warned_missing_proto = true;
        }
        return post_process(app_ctx, outputs, letter_box, conf_threshold, nms_threshold, bbox_fallback);
    }

    rknn_output *_outputs = (rknn_output *)outputs;
    const int model_in_w = app_ctx->model_width;
    const int model_in_h = app_ctx->model_height;
    std::vector<Yolov8SegCandidate> candidates;
    int ret = 0;

    if (app_ctx->io_num.n_output == 2)
    {
        const int pred_index = proto_index == 0 ? 1 : 0;
        ret = process_yolov8_combined_seg_output(_outputs[pred_index].buf,
                                                 &app_ctx->output_attrs[pred_index],
                                                 proto_layout.mask_dim,
                                                 conf_threshold,
                                                 candidates);
    }
    else if (app_ctx->io_num.n_output >= 4)
    {
        int box_index = -1;
        int score_index = -1;
        int coeff_index = -1;
        int box_channels = 0;
        int box_anchors = 0;
        int score_channels = 0;
        int score_anchors = 0;
        int coeff_channels = 0;
        int coeff_anchors = 0;
        bool box_channel_first = true;
        bool score_channel_first = true;
        bool coeff_channel_first = true;

        for (int i = 0; i < app_ctx->io_num.n_output; ++i)
        {
            if (i == proto_index)
            {
                continue;
            }
            rknn_tensor_attr *attr = &app_ctx->output_attrs[i];
            int channels = 0;
            int anchors = 0;
            bool channel_first = true;
            if (box_index < 0 && tensor_name_contains(attr, "box") &&
                yolov8_parse_shape(attr, 4, &channels, &anchors, &channel_first))
            {
                box_index = i;
                box_channels = channels;
                box_anchors = anchors;
                box_channel_first = channel_first;
                continue;
            }
            if (score_index < 0 && tensor_name_contains(attr, "score") &&
                yolov8_parse_rank3_shape(attr, &channels, &anchors, &channel_first))
            {
                score_index = i;
                score_channels = channels;
                score_anchors = anchors;
                score_channel_first = channel_first;
                continue;
            }
            if (coeff_index < 0 &&
                (tensor_name_contains(attr, "coeff") || tensor_name_contains(attr, "mask")) &&
                yolov8_parse_shape(attr, proto_layout.mask_dim, &channels, &anchors, &channel_first))
            {
                coeff_index = i;
                coeff_channels = channels;
                coeff_anchors = anchors;
                coeff_channel_first = channel_first;
                continue;
            }
        }

        for (int i = 0; i < app_ctx->io_num.n_output; ++i)
        {
            if (i == proto_index)
            {
                continue;
            }
            rknn_tensor_attr *attr = &app_ctx->output_attrs[i];
            int channels = 0;
            int anchors = 0;
            bool channel_first = true;
            if (box_index < 0 && yolov8_parse_shape(attr, 4, &channels, &anchors, &channel_first))
            {
                box_index = i;
                box_channels = channels;
                box_anchors = anchors;
                box_channel_first = channel_first;
                continue;
            }
            if (coeff_index < 0 && yolov8_parse_shape(attr, proto_layout.mask_dim, &channels, &anchors, &channel_first))
            {
                coeff_index = i;
                coeff_channels = channels;
                coeff_anchors = anchors;
                coeff_channel_first = channel_first;
            }
        }

        for (int i = 0; i < app_ctx->io_num.n_output; ++i)
        {
            if (i == proto_index || i == box_index || i == coeff_index)
            {
                continue;
            }
            rknn_tensor_attr *attr = &app_ctx->output_attrs[i];
            int channels = 0;
            int anchors = 0;
            bool channel_first = true;
            if (yolov8_parse_rank3_shape(attr, &channels, &anchors, &channel_first))
            {
                score_index = i;
                score_channels = channels;
                score_anchors = anchors;
                score_channel_first = channel_first;
                break;
            }
        }

        if (box_index < 0 || score_index < 0 || coeff_index < 0 ||
            box_anchors != score_anchors || box_anchors != coeff_anchors)
        {
            static bool warned_bad_split = false;
            if (!warned_bad_split)
            {
                printf("YOLOv8-seg postprocess: expected boxes/scores/mask_coeffs/protos outputs but got %d tensors\n",
                       app_ctx->io_num.n_output);
                warned_bad_split = true;
            }
            return -1;
        }

        ret = process_yolov8_split_seg_outputs(_outputs[box_index].buf, &app_ctx->output_attrs[box_index],
                                               box_channels, box_anchors, box_channel_first,
                                               _outputs[score_index].buf, &app_ctx->output_attrs[score_index],
                                               score_channels, score_channel_first,
                                               _outputs[coeff_index].buf, &app_ctx->output_attrs[coeff_index],
                                               coeff_channels, coeff_channel_first,
                                               conf_threshold, candidates);
    }
    else
    {
        static bool warned_unsupported = false;
        if (!warned_unsupported)
        {
            printf("YOLOv8-seg postprocess: unsupported output count=%d; output shape needs inspection\n",
                   app_ctx->io_num.n_output);
            warned_unsupported = true;
        }
        return -1;
    }

    if (ret < 0)
    {
        static bool warned_parse_failed = false;
        if (!warned_parse_failed)
        {
            printf("YOLOv8-seg postprocess: prediction parse failed; output shape needs inspection\n");
            warned_parse_failed = true;
        }
        return -1;
    }

    std::vector<int> selected_indices;
    select_seg_candidates_after_nms(candidates, letter_box, nms_threshold,
                                    model_in_w, model_in_h, bbox_fallback, &selected_indices);

    bool all_real_masks = bbox_fallback->count > 0;
    seg_results->count = bbox_fallback->count;
    for (int i = 0; i < bbox_fallback->count && i < OBJ_NUMB_MAX_SIZE; ++i)
    {
        object_seg_result *seg = &seg_results->results[i];
        seg->det = bbox_fallback->results[i];
        seg->has_mask = 0;
        seg->mask_width = proto_layout.width;
        seg->mask_height = proto_layout.height;
        seg->contour_count = 0;
        memset(seg->contours, 0, sizeof(seg->contours));

        bool real_mask = false;
        if (i < (int)selected_indices.size())
        {
            const int candidate_index = selected_indices[i];
            if (candidate_index >= 0 && candidate_index < (int)candidates.size())
            {
                real_mask = build_mask_contour_from_proto(candidates[candidate_index],
                                                          _outputs[proto_index].buf,
                                                          &app_ctx->output_attrs[proto_index],
                                                          proto_layout,
                                                          letter_box,
                                                          model_in_w,
                                                          model_in_h,
                                                          seg);
            }
        }
        if (!real_mask)
        {
            all_real_masks = false;
        }
    }
    seg_results->mask_status = all_real_masks ? 0 : 1;
    return 0;
#endif
}

int init_post_process()
{
    int ret = 0;
    ret = loadLabelName(LABEL_NALE_TXT_PATH, labels);
    if (ret < 0)
    {
        printf("Load %s failed!\n", LABEL_NALE_TXT_PATH);
        return -1;
    }
    return 0;
}

char *coco_cls_to_name(int cls_id)
{

    if (cls_id >= OBJ_CLASS_NUM)
    {
        return "null";
    }

    if (labels[cls_id])
    {
        return labels[cls_id];
    }

    return "null";
}

void deinit_post_process()
{
    for (int i = 0; i < OBJ_CLASS_NUM; i++)
    {
        if (labels[i] != nullptr)
        {
            free(labels[i]);
            labels[i] = nullptr;
        }
    }
}
