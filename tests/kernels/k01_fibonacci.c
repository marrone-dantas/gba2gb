/* Fibonacci iterativo, n limitado a 0..47 */
int f(int r0,int r1,int r2,int r3){ unsigned n=r0&47,a=0,b=1; while(n--){unsigned t=a+b;a=b;b=t;} return a; }
