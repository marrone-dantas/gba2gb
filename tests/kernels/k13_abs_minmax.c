/* abs, min, max com sinal e sem sinal */
int f(int r0,int r1,int r2,int r3){ int a=r0<0?-r0:r0; int mn=r1<r2?r1:r2; unsigned mx=(unsigned)r2>(unsigned)r3?r2:r3; return a+mn+mx; }
