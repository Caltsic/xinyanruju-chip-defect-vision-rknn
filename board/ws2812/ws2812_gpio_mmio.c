#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define GPIO_PORT_DR 0x00u
#define GPIO_PORT_DDR 0x08u
#define GPIO_MAP_BYTES 0x1000u

#define WS2812_T0H_NS 400u
#define WS2812_T1H_NS 800u
#define WS2812_PERIOD_NS 1250u
#define WS2812_RESET_US 80u

struct options {
    uint64_t base;
    bool have_base;
    unsigned int line;
    bool have_line;
    int count;
    int red;
    int green;
    int blue;
    double brightness;
    bool off;
};

struct gpio_map {
    int fd;
    void *mapping;
    size_t map_size;
    volatile uint32_t *regs;
};

static void usage(const char *program)
{
    fprintf(
        stderr,
        "Usage: %s --base 0xADDR --line N --count N [--rgb R,G,B] [--brightness F] [--off]\n",
        program);
}

static int parse_u64(const char *text, uint64_t *out)
{
    char *end = NULL;
    errno = 0;
    unsigned long long value = strtoull(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0') {
        return -1;
    }
    *out = (uint64_t)value;
    return 0;
}

static int parse_int(const char *text, int *out)
{
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0') {
        return -1;
    }
    *out = (int)value;
    return 0;
}

static int parse_double(const char *text, double *out)
{
    char *end = NULL;
    errno = 0;
    double value = strtod(text, &end);
    if (errno != 0 || end == text || *end != '\0') {
        return -1;
    }
    *out = value;
    return 0;
}

static int parse_rgb(const char *text, int *red, int *green, int *blue)
{
    char *copy = strdup(text);
    if (copy == NULL) {
        return -1;
    }

    int values[3] = {0, 0, 0};
    char *cursor = copy;
    for (int i = 0; i < 3; ++i) {
        char *token = strsep(&cursor, ",;");
        if (token == NULL || parse_int(token, &values[i]) != 0 || values[i] < 0 || values[i] > 255) {
            free(copy);
            return -1;
        }
    }
    if (cursor != NULL && *cursor != '\0') {
        free(copy);
        return -1;
    }

    *red = values[0];
    *green = values[1];
    *blue = values[2];
    free(copy);
    return 0;
}

static int clamp_u8_from_scaled(int value, double brightness)
{
    int scaled = (int)(value * brightness + 0.5);
    if (scaled < 0) {
        return 0;
    }
    if (scaled > 255) {
        return 255;
    }
    return scaled;
}

static int parse_args(int argc, char **argv, struct options *opts)
{
    static const struct option long_options[] = {
        {"base", required_argument, NULL, 'b'},
        {"line", required_argument, NULL, 'l'},
        {"count", required_argument, NULL, 'c'},
        {"rgb", required_argument, NULL, 'r'},
        {"brightness", required_argument, NULL, 'B'},
        {"off", no_argument, NULL, 'o'},
        {"help", no_argument, NULL, 'h'},
        {NULL, 0, NULL, 0},
    };

    opts->count = 256;
    opts->red = 190;
    opts->green = 255;
    opts->blue = 100;
    opts->brightness = 0.20;

    for (;;) {
        int opt = getopt_long(argc, argv, "", long_options, NULL);
        if (opt == -1) {
            break;
        }
        switch (opt) {
        case 'b':
            if (parse_u64(optarg, &opts->base) != 0) {
                fprintf(stderr, "invalid --base value: %s\n", optarg);
                return -1;
            }
            opts->have_base = true;
            break;
        case 'l': {
            int line = -1;
            if (parse_int(optarg, &line) != 0 || line < 0 || line > 31) {
                fprintf(stderr, "invalid --line value: %s (expected 0..31)\n", optarg);
                return -1;
            }
            opts->line = (unsigned int)line;
            opts->have_line = true;
            break;
        }
        case 'c':
            if (parse_int(optarg, &opts->count) != 0 || opts->count <= 0) {
                fprintf(stderr, "invalid --count value: %s (expected > 0)\n", optarg);
                return -1;
            }
            break;
        case 'r':
            if (parse_rgb(optarg, &opts->red, &opts->green, &opts->blue) != 0) {
                fprintf(stderr, "invalid --rgb value: %s (expected R,G,B in 0..255)\n", optarg);
                return -1;
            }
            break;
        case 'B':
            if (parse_double(optarg, &opts->brightness) != 0 || opts->brightness < 0.0 || opts->brightness > 1.0) {
                fprintf(stderr, "invalid --brightness value: %s (expected 0.0..1.0)\n", optarg);
                return -1;
            }
            break;
        case 'o':
            opts->off = true;
            break;
        case 'h':
            usage(argv[0]);
            exit(0);
        default:
            usage(argv[0]);
            return -1;
        }
    }

    if (!opts->have_base) {
        fprintf(stderr, "missing required --base\n");
        return -1;
    }
    if (!opts->have_line) {
        fprintf(stderr, "missing required --line\n");
        return -1;
    }
    return 0;
}

static void try_realtime_setup(void)
{
    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        fprintf(stderr, "warning: mlockall failed: %s\n", strerror(errno));
    }

    struct sched_param param;
    memset(&param, 0, sizeof(param));
    param.sched_priority = 80;
    if (sched_setscheduler(0, SCHED_FIFO, &param) != 0) {
        fprintf(stderr, "warning: sched_setscheduler(SCHED_FIFO) failed: %s\n", strerror(errno));
    }
}

static int map_gpio(uint64_t base, struct gpio_map *map)
{
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        fprintf(stderr, "failed to get page size\n");
        return -1;
    }

    uint64_t page_mask = (uint64_t)page_size - 1u;
    uint64_t page_base = base & ~page_mask;
    uint64_t page_offset = base - page_base;
    map->map_size = (size_t)page_offset + GPIO_MAP_BYTES;

    map->fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (map->fd < 0) {
        fprintf(stderr, "failed to open /dev/mem: %s\n", strerror(errno));
        return -1;
    }

    map->mapping = mmap(NULL, map->map_size, PROT_READ | PROT_WRITE, MAP_SHARED, map->fd, (off_t)page_base);
    if (map->mapping == MAP_FAILED) {
        fprintf(stderr, "failed to mmap GPIO base 0x%llx: %s\n", (unsigned long long)base, strerror(errno));
        close(map->fd);
        map->fd = -1;
        return -1;
    }

    map->regs = (volatile uint32_t *)((uint8_t *)map->mapping + page_offset);
    return 0;
}

static void unmap_gpio(struct gpio_map *map)
{
    if (map->mapping != NULL && map->mapping != MAP_FAILED) {
        munmap(map->mapping, map->map_size);
    }
    if (map->fd >= 0) {
        close(map->fd);
    }
}

static inline void gpio_write_masked(volatile uint32_t *regs, unsigned int offset, unsigned int line, int value)
{
    unsigned int reg_offset = offset + ((line >= 16u) ? 4u : 0u);
    unsigned int bit = line & 15u;
    uint32_t mask = 1u << bit;
    uint32_t data = value ? mask : 0u;
    regs[reg_offset / 4u] = (mask << 16) | data;
}

static inline void gpio_set_output(volatile uint32_t *regs, unsigned int line)
{
    gpio_write_masked(regs, GPIO_PORT_DDR, line, 1);
}

static inline void gpio_set_level(volatile uint32_t *regs, unsigned int line, int value)
{
    gpio_write_masked(regs, GPIO_PORT_DR, line, value);
}

#if defined(__aarch64__)
static uint64_t timer_frequency_hz;
static uint64_t timer_period_ticks;
static uint64_t timer_t0h_ticks;
static uint64_t timer_t1h_ticks;

static inline uint64_t read_arch_counter(void)
{
    uint64_t value;
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(value));
    return value;
}

static inline uint64_t read_arch_frequency(void)
{
    uint64_t value;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(value));
    return value;
}

static uint64_t ns_to_ticks(uint32_t ns)
{
    return ((uint64_t)ns * timer_frequency_hz + 999999999ull) / 1000000000ull;
}

static inline void wait_until_tick(uint64_t target)
{
    while (read_arch_counter() < target) {
    }
}

static void send_bit(volatile uint32_t *regs, unsigned int line, int bit)
{
    uint64_t high = bit ? timer_t1h_ticks : timer_t0h_ticks;
    uint64_t start_tick = read_arch_counter();
    gpio_set_level(regs, line, 1);
    wait_until_tick(start_tick + high);
    gpio_set_level(regs, line, 0);
    wait_until_tick(start_tick + timer_period_ticks);
}
#else
static uint64_t now_ns(void)
{
    struct timespec ts;
#if defined(CLOCK_MONOTONIC_RAW)
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
    clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static inline void wait_until_ns(uint64_t target)
{
    while (now_ns() < target) {
    }
}

static void send_bit(volatile uint32_t *regs, unsigned int line, int bit)
{
    uint64_t start_ns = now_ns();
    gpio_set_level(regs, line, 1);
    wait_until_ns(start_ns + (bit ? WS2812_T1H_NS : WS2812_T0H_NS));
    gpio_set_level(regs, line, 0);
    wait_until_ns(start_ns + WS2812_PERIOD_NS);
}
#endif

static void send_byte(volatile uint32_t *regs, unsigned int line, uint8_t value)
{
    for (int bit = 7; bit >= 0; --bit) {
        send_bit(regs, line, (value & (1u << bit)) != 0);
    }
}

static void send_pixels(volatile uint32_t *regs, unsigned int line, int count, uint8_t red, uint8_t green, uint8_t blue)
{
    gpio_set_level(regs, line, 0);
    usleep(WS2812_RESET_US);

    for (int i = 0; i < count; ++i) {
        send_byte(regs, line, green);
        send_byte(regs, line, red);
        send_byte(regs, line, blue);
    }

    gpio_set_level(regs, line, 0);
    usleep(WS2812_RESET_US);
}

int main(int argc, char **argv)
{
    struct options opts;
    memset(&opts, 0, sizeof(opts));
    if (parse_args(argc, argv, &opts) != 0) {
        usage(argv[0]);
        return 2;
    }

    int red = opts.off ? 0 : clamp_u8_from_scaled(opts.red, opts.brightness);
    int green = opts.off ? 0 : clamp_u8_from_scaled(opts.green, opts.brightness);
    int blue = opts.off ? 0 : clamp_u8_from_scaled(opts.blue, opts.brightness);

#if defined(__aarch64__)
    timer_frequency_hz = read_arch_frequency();
    if (timer_frequency_hz == 0) {
        fprintf(stderr, "failed to read ARM generic timer frequency\n");
        return 2;
    }
    timer_period_ticks = ns_to_ticks(WS2812_PERIOD_NS);
    timer_t0h_ticks = ns_to_ticks(WS2812_T0H_NS);
    timer_t1h_ticks = ns_to_ticks(WS2812_T1H_NS);
#endif

    try_realtime_setup();

    struct gpio_map gpio;
    memset(&gpio, 0, sizeof(gpio));
    gpio.fd = -1;
    if (map_gpio(opts.base, &gpio) != 0) {
        return 1;
    }

    gpio_set_output(gpio.regs, opts.line);
    send_pixels(gpio.regs, opts.line, opts.count, (uint8_t)red, (uint8_t)green, (uint8_t)blue);
    unmap_gpio(&gpio);

    printf(
        "ws2812-gpio-mmio count=%d line=%u brightness=%.3f rgb=(%d, %d, %d) base=0x%llx\n",
        opts.count,
        opts.line,
        opts.brightness,
        red,
        green,
        blue,
        (unsigned long long)opts.base);
    return 0;
}
