/* Laço aninhado tipo varredura de tilemap 8x8 com contagem condicional */
int f(int r0,int r1,int r2,int r3){ int cnt=0; unsigned seed=r0;
 for(int y=0;y<8;y++) for(int x=0;x<8;x++){ seed=seed*1103515245u+12345u; if(((seed>>16)&15) < (unsigned)(r1&15)) cnt+=x^y; }
 return cnt ^ (seed>>8); }
