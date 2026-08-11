#include "msxgl.h"

#include "sdcc/include/stdint.h"

// VRAM copy in ROM (storage space written to by python script)
const uint8_t IMAGE[16384] = { 0x00 };

// global variable vblank
bool vblank_status = false;

void vblank_hook()
{
	vblank_status = true;
}

void wait_vblank()
{
	while (vblank_status == false) {}
	vblank_status = false;
}

int main(void)
{
	//VDP_EnableDisplay(false);

	VDP_SetMode(VDP_MODE_GRAPHIC2); // VDP_MODE_SCREEN2);
	VDP_SetColor(0x11);

	VDP_DisableSpritesFrom(0);

	//VDP_SetGrayScale(true);

	//wait_vblank();
	VDP_WriteVRAM_16K(IMAGE, 0, 16384);

	BIOS_SetHookCallback(H_TIMI, vblank_hook);
	VDP_EnableVBlank(true);

	//VDP_EnableDisplay(true);

	while (true) {
		// frame 0
		wait_vblank();
		VDP_SetLayoutTable(0x1800);

		// frame 1
		wait_vblank();
		VDP_SetLayoutTable(0x1c00);
	}

	// never reached
	BIOS_ClearHook(H_TIMI);
	BIOS_Exit(0);
	return 0;
}
