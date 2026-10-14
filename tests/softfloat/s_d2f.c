/* lockstep kernel for __aeabi_d2f (tests/test_softfloat.py) */
typedef unsigned u32; typedef unsigned long long u64;
#define F __aeabi_d2f
#define J(lo,hi) (((u64)(hi)<<32)|(lo))
u32 F(u64);
u64 f(u32 a,u32 b){return F(J(a,b));}
