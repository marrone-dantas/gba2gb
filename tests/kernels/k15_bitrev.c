/* 32-bit bit reversal */
int f(int r0,int r1,int r2,int r3){ unsigned x=r0,r=0; for(int i=0;i<32;i++){r=(r<<1)|(x&1);x>>=1;} return r; }
