/* lockstep kernel for __aeabi_fmul (tests/test_softfloat.py) */
typedef unsigned u32; typedef unsigned long long u64;
#define F __aeabi_fmul
#define J(lo,hi) (((u64)(hi)<<32)|(lo))
u32 F(u32,u32);
u64 f(u32 a,u32 b){return F(a,b);}
