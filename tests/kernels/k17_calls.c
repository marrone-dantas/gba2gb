/* BL calls to non-inlined helper functions */
__attribute__((noinline)) static int sq(int x){ return x*x; }
__attribute__((noinline)) static int mix(int a,int b){ return (a<<3)^(b>>2)^(a+b); }
int f(int r0,int r1,int r2,int r3){ return mix(sq(r0&0xFFF), r1) + mix(r2, sq(r3&0xFF)); }
