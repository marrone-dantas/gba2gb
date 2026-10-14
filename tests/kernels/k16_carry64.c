/* 64-bit add and subtract (ADC/SBC) */
int f(int r0,int r1,int r2,int r3){ unsigned long long a=((unsigned long long)(unsigned)r1<<32)|(unsigned)r0;
 unsigned long long b=((unsigned long long)(unsigned)r3<<32)|(unsigned)r2; unsigned long long s=a+b, d=a-b;
 return (int)(s>>32) ^ (int)d ^ (int)(d>>32); }
