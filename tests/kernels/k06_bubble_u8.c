/* Bubble sort of 8 unsigned bytes; returns the 4 smallest packed */
int f(int r0,int r1,int r2,int r3){ unsigned char a[8]; unsigned v0=r0,v1=r1; int i,j;
 for(i=0;i<4;i++){a[i]=v0>>(8*i);a[i+4]=v1>>(8*i);}
 for(i=0;i<7;i++) for(j=0;j<7-i;j++) if(a[j]>a[j+1]){unsigned char t=a[j];a[j]=a[j+1];a[j+1]=t;}
 return a[0]|(a[1]<<8)|(a[2]<<16)|(a[3]<<24); }
