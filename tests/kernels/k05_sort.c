/* Insertion sort of 8 stack elements; returns a hash of the order */
int f(int r0,int r1,int r2,int r3){ int a[8]={r0,r1,r2,r3,r0^r1,r2-r3,r1+r3,r0-r2}; int i,j;
 for(i=1;i<8;i++){ int k=a[i]; j=i-1; while(j>=0&&a[j]>k){a[j+1]=a[j];j--;} a[j+1]=k; }
 unsigned h=0; for(i=0;i<8;i++) h=h*31+a[i]; return h; }
