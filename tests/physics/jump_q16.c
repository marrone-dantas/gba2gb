/* Jump parabola with gravity, ground bounce and friction in Q16.16 fixed point.
 * f(n, axis, 0, 0): simulates n frames and returns the screen position in pixels
 * (axis 0: height y above ground, axis 1: horizontal x).
 * All constants are multiples of 1/256 so that the opt-in Q8.8 requantization of
 * tools/prune/bitwidth_pruning.py can represent them exactly. */
#define FX(v) ((int)((v) * 65536))
#define GRAVITY   FX(0.25)
#define JUMP_VY   FX(6.0)
#define START_VX  FX(2.5)
#define FRICTION  FX(0.015625)
#define REJUMP_VY FX(1.0)

int f(int n, int axis, int r2, int r3) {
    int x = 0, y = 0, vx = START_VX, vy = JUMP_VY;
    for (int i = 0; i < n; i++) {
        vy -= GRAVITY;
        y += vy;
        if (y < 0) {                         /* ground hit: bounce with 3/4 energy */
            y = 0;
            vy = -(vy - (vy >> 2));
            if (vy < REJUMP_VY) vy = JUMP_VY;  /* small bounce: jump again */
        }
        if (vx > FRICTION) vx -= FRICTION; else vx = 0;
        x += vx;
    }
    return axis ? (x >> 16) : (y >> 16);
}
