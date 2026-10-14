/* Raiz quadrada inteira por bits */
int f(int r0,int r1,int r2,int r3){ unsigned x=(unsigned)r0>>2, res=0, bit=1u<<30;
 while(bit>x) bit>>=2;
 while(bit){ if(x>=res+bit){x-=res+bit;res=(res>>1)+bit;} else res>>=1; bit>>=2; } return res; }
