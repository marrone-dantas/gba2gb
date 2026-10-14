"""Phase 3.5 metrics.

ssim_luma     SSIM (skimage, 7x7 window, data range 1) between the original luminance and
              the reconstruction with each DMG level shown at the least-squares monotone tone
              (mean original luminance of the pixels using that level, see tone()); i.e. the
              structure kept by the 4-level tiles, independent of the LCD's grey values.
              This is the target metric (>= 0.82 mean).
ssim_display  same, but the reconstruction shown with the fixed DMG shades 1, 2/3, 1/3, 0
              (reported; includes the global tone change of a dark scene to DMG greys).
edge_iou      on pixels of solid (collision) 8x8 cells. Edge map of an image: pixel p is an
              edge if it differs from one of its 4 neighbours by more than t
              (original luminance: t = 0.05; reconstruction: any DMG level change, i.e. a
              visible shade step of >= 1/3). Contrast-independent, so the 4-level
              contrast stretch neither adds nor removes edges by itself;
              IoU = |A & B| / |A | B| (1.0 when both are empty)."""
import numpy as np
from skimage.metrics import structural_similarity
from .vq_tile_compiler import sobel_mag, shade

EDGE_T = 0.05


def ssim(a, b):
    return float(structural_similarity(a, b, data_range=1.0, win_size=7))


def tone(res):
    """Least-squares monotone tone map: per DMG level, the mean original luminance of the
    pixels shown with that level (levels without pixels: compiler centre), made
    non-increasing (level 0 brightest)."""
    y, r = res["y"], res["recon"]
    c = np.array(res["stats"]["centres"], float)
    for l in range(4):
        m = r == l
        if m.any():
            c[l] = y[m].mean()
    for l in range(1, 4):
        c[l] = min(c[l], c[l - 1])
    return c


def centre_image(res):
    return tone(res)[res["recon"]]


def edges(img, t):
    e = np.zeros(img.shape, bool)
    dx = np.abs(np.diff(img, axis=1)) > t
    dy = np.abs(np.diff(img, axis=0)) > t
    e[:, :-1] |= dx
    e[:, 1:] |= dx
    e[:-1, :] |= dy
    e[1:, :] |= dy
    return e


def edge_iou(y, levels, mask, t=EDGE_T):
    ea, eb = edges(y, t), edges(np.asarray(levels, float), 0.5)
    ea, eb = ea & mask, eb & mask
    u = (ea | eb).sum()
    return 1.0 if u == 0 else float((ea & eb).sum() / u)


def solid_pixel_mask(res):
    h, w = res["recon"].shape
    c = res["cells_solid"].reshape(h // 8, w // 8)
    return np.kron(c, np.ones((8, 8), bool))


def scene_metrics(res):
    r = centre_image(res)
    m = solid_pixel_mask(res)
    return {"ssim_luma": ssim(res["y"], r), "ssim_display": ssim(res["y"], shade(res["recon"])),
            "edge_iou_solid": edge_iou(res["y"], res["recon"], m), "solid_cells": int(res["cells_solid"].sum())}
