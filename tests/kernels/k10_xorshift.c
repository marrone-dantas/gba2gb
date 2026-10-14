/* PRNG xorshift32, 8 iterações */
int f(int r0,int r1,int r2,int r3){ unsigned x=r0|1; for(int i=0;i<8;i++){x^=x<<13;x^=x>>17;x^=x<<5;} return x; }
