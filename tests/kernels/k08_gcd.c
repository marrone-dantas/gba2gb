/* MDC por subtração (sem divisão) */
int f(int r0,int r1,int r2,int r3){ unsigned a=(r0&1023)+1,b=(r1&1023)+1; while(a!=b){ if(a>b)a-=b; else b-=a;} return a; }
