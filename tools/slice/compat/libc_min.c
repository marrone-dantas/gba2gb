/* Minimal C library for homebrew builds: newlib-compatible rand/srand (64-bit LCG),
   byte-wise memcpy/memset (no word tricks: keeps the lifted code small). */
#include <stddef.h>
static unsigned long long rand_next = 1;
void srand(unsigned int seed) { rand_next = seed; }
int rand(void)
{
    rand_next = rand_next * 6364136223846793005ULL + 1;
    return (int)((rand_next >> 32) & 0x7FFFFFFF);
}
void *memcpy(void *d, const void *s, size_t n)
{
    unsigned char *dp = d; const unsigned char *sp = s;
    while (n--) *dp++ = *sp++;
    return d;
}
void *memset(void *d, int c, size_t n)
{
    unsigned char *dp = d;
    while (n--) *dp++ = (unsigned char)c;
    return d;
}
