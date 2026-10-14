/* Contagem de bits de r0^r1 */
int f(int r0,int r1,int r2,int r3){ unsigned x=r0^r1; int c=0; while(x){x&=x-1;c++;} return c; }
