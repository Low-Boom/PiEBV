// Compiler and platform settings that lwIP asks for (tools/net_check/lwip).
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define LWIP_PLATFORM_DIAG(x) do { printf x; } while (0)
#define LWIP_PLATFORM_ASSERT(x) do { printf("LWIP ASSERT: %s (%s:%d)\n", x, __FILE__, __LINE__); abort(); } while (0)
#define LWIP_NO_CTYPE_H 0
#ifdef __cplusplus
extern "C" {
#endif
unsigned int lwip_test_rand(void);
#ifdef __cplusplus
}
#endif
#define LWIP_RAND() lwip_test_rand()
