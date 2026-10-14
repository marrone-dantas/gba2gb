/* Headless GBA snapshot capturer on libmgba (Phase 3, commercial evaluation).
 *
 * Usage: mgba_capture ROM SCRIPT OUTDIR
 * SCRIPT lines (one command per line, '#' comments):
 *   run N              run N frames with no keys
 *   hold KEYS N        hold KEYS (e.g. A+RIGHT) for N frames
 *   tap KEYS           hold KEYS 2 frames, then release 10 frames
 *   save NAME / load NAME   save state OUTDIR/NAME.ss0
 *   poke8 ADDR VAL / poke16 ADDR VAL   write memory (cheats / scene setup)
 *   memdump NAME       write OUTDIR/NAME/{ewram,iwram}.bin (for RAM searches)
 *   snap NAME          write OUTDIR/NAME/{vram,pal,io,oam}.bin + screen.ppm + meta.json
 *                      (tools/vq/snapshot.py directory format)
 * Keys: A B SELECT START RIGHT LEFT UP DOWN R L.
 * IO is taken from mGBA's register file (memory.io), which keeps the last value written
 * to write-only registers such as BGxHOFS. */
#include <mgba/core/core.h>
#include <mgba/core/serialize.h>
#include <mgba/internal/gba/gba.h>
#include <mgba-util/vfs.h>
#include <mgba/core/log.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static struct mCore* core;
static color_t* fb;
static const char* outdir;
static long frame;

static int keymask(const char* s) {
	static const char* names[] = { "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L" };
	int m = 0;
	char buf[128];
	strncpy(buf, s, sizeof(buf) - 1);
	buf[sizeof(buf) - 1] = 0;
	for (char* t = strtok(buf, "+"); t; t = strtok(NULL, "+")) {
		int found = 0;
		for (int i = 0; i < 10; ++i) {
			if (!strcmp(t, names[i])) { m |= 1 << i; found = 1; }
		}
		if (!found && strcmp(t, "NONE")) { fprintf(stderr, "bad key %s\n", t); exit(2); }
	}
	return m;
}

static void frames(int keys, int n) {
	core->setKeys(core, keys);
	for (int i = 0; i < n; ++i) { core->runFrame(core); ++frame; }
}

static void wfile(const char* dir, const char* name, const void* p, size_t n) {
	char path[1024];
	snprintf(path, sizeof(path), "%s/%s", dir, name);
	FILE* f = fopen(path, "wb");
	fwrite(p, 1, n, f);
	fclose(f);
}

static void snap(const char* name) {
	struct GBA* gba = core->board;
	char dir[1024];
	snprintf(dir, sizeof(dir), "%s/%s", outdir, name);
	mkdir(dir, 0755);
	wfile(dir, "vram.bin", gba->video.vram, 0x18000);
	wfile(dir, "pal.bin", gba->video.palette, 0x400);
	wfile(dir, "io.bin", gba->memory.io, 0x400);
	wfile(dir, "oam.bin", gba->video.oam.raw, 0x400);
	char path[1024];
	snprintf(path, sizeof(path), "%s/screen.ppm", dir);
	FILE* f = fopen(path, "wb");
	fprintf(f, "P6 240 160 255\n");
	for (int i = 0; i < 240 * 160; ++i) {
		color_t c = fb[i];   /* mGBA 32-bit colour: 0xXXBBGGRR */
		unsigned char px[3] = { c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF };
		fwrite(px, 1, 3, f);
	}
	fclose(f);
	snprintf(path, sizeof(path), "%s/meta.json", dir);
	f = fopen(path, "w");
	fprintf(f, "{\"name\": \"%s\", \"source\": \"mgba_capture frame %ld\"}\n", name, frame);
	fclose(f);
	fprintf(stderr, "snap %s at frame %ld\n", name, frame);
}

static void state(const char* name, int save) {
	char path[1024];
	snprintf(path, sizeof(path), "%s/%s.ss0", outdir, name);
	struct VFile* vf = VFileOpen(path, save ? O_CREAT | O_TRUNC | O_RDWR : O_RDONLY);
	if (!vf) { fprintf(stderr, "cannot open %s\n", path); exit(3); }
	int ok = save ? mCoreSaveStateNamed(core, vf, SAVESTATE_SAVEDATA) : mCoreLoadStateNamed(core, vf, SAVESTATE_SAVEDATA);
	vf->close(vf);
	if (!ok) { fprintf(stderr, "state %s failed\n", name); exit(3); }
}

static void quiet(struct mLogger* l, int cat, enum mLogLevel lv, const char* fmt, va_list a) {
	(void) l; (void) cat; (void) lv; (void) fmt; (void) a;
}
static struct mLogger nolog = { .log = quiet };

int main(int argc, char** argv) {
	mLogSetDefaultLogger(&nolog);
	if (argc < 4) { fprintf(stderr, "usage: %s ROM SCRIPT OUTDIR\n", argv[0]); return 1; }
	outdir = argv[3];
	mkdir(outdir, 0755);
	core = mCoreFind(argv[1]);
	if (!core || !core->init(core)) { fprintf(stderr, "no core\n"); return 1; }
	mCoreInitConfig(core, NULL);
	fb = calloc(256 * 256, sizeof(color_t));
	core->setVideoBuffer(core, fb, 240);
	if (!mCoreLoadFile(core, argv[1])) { fprintf(stderr, "cannot load ROM\n"); return 1; }
	core->reset(core);
	FILE* s = strcmp(argv[2], "-") ? fopen(argv[2], "r") : stdin;
	char line[512], cmd[64], a1[256];
	int n;
	while (fgets(line, sizeof(line), s)) {
		char* h = strchr(line, '#');
		if (h) *h = 0;
		int k = sscanf(line, "%63s %255s %d", cmd, a1, &n);
		if (k < 1) continue;
		if (!strcmp(cmd, "run")) frames(0, atoi(a1));
		else if (!strcmp(cmd, "hold")) frames(keymask(a1), n);
		else if (!strcmp(cmd, "tap")) { frames(keymask(a1), 2); frames(0, 10); }
		else if (!strcmp(cmd, "snap")) snap(a1);
		else if (!strcmp(cmd, "save")) state(a1, 1);
		else if (!strcmp(cmd, "load")) state(a1, 0);
		else if (!strcmp(cmd, "poke8") || !strcmp(cmd, "poke16")) {
			unsigned addr = strtoul(a1, NULL, 0), val;
			sscanf(line, "%*s %*s %i", (int*) &val);
			if (cmd[4] == '8') core->rawWrite8(core, addr, -1, val);
			else core->rawWrite16(core, addr, -1, val);
		}
		else if (!strcmp(cmd, "memdump")) {
			struct GBA* gba = core->board;
			char dir[1024];
			snprintf(dir, sizeof(dir), "%s/%s", outdir, a1);
			mkdir(dir, 0755);
			wfile(dir, "ewram.bin", gba->memory.wram, 0x40000);
			wfile(dir, "iwram.bin", gba->memory.iwram, 0x8000);
		}
		else { fprintf(stderr, "bad command %s\n", cmd); return 2; }
	}
	core->deinit(core);
	return 0;
}
