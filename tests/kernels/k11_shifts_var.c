/* Register-amount shifts (including >=32) */
int f(int r0,int r1,int r2,int r3){ unsigned s=r1&63; unsigned a=(unsigned)r0<<(s&31), b=(unsigned)r0>>(r2&31); int c=r0>>(r3&31);
 return a ^ b ^ c ^ (s>31); }
