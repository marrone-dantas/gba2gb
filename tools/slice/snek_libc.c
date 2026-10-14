/* Phase 5 B1: minimal C library for the Snek GBA build (instead of newlib's
   reentrant stdio-dependent rand). Same algorithm and state as newlib's rand(3):
   64-bit LCG next = next * 6364136223846793005 + 1, result (next >> 32) & RAND_MAX,
   srand(seed) sets next = seed, initial next = 1. */
static unsigned long long rand_next = 1;

void srand(unsigned int seed)
{
    rand_next = seed;
}

int rand(void)
{
    rand_next = rand_next * 6364136223846793005ULL + 1;
    return (int)((rand_next >> 32) & 0x7FFFFFFF);
}
