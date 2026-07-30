TileViewer = class {
    constructor() {
        this.controller = null;
    }

    initialize(options) {
        this.canvas = document.getElementById(options.canvasId);
        this.ctx = this.canvas.getContext("2d");
        this.ctx.imageSmoothingEnabled = false;
        this.selectedX = options.selectedX;
        this.selectedY = options.selectedY;
        this.gridWidth = options.gridWidth;
        this.gridHeight = options.gridHeight;
        this.zoom = options.zoom;
        this.image = new Image();
        this.image.onload = () => {
            this.draw();
        };
        this.image.src = options.image;
        this.installEvents();
    }

    reset() {
        this.ctx.reset();
        this.removeEvents();
    }

    setState(state) {
        this.zoom = state.zoom;
        this.selectedX = state.selectedX;
        this.selectedY = state.selectedY;
        this.gridWidth = state.gridWidth;
        this.gridHeight = state.gridHeight;
    }

    draw() {
        this.canvas.width = this.image.width * this.zoom;
        this.canvas.height = this.image.height * this.zoom;
        this.drawImage();
        this.drawGrid();
        // this.drawSelection();
    }

    drawImage() {
        this.ctx.drawImage(
            this.image,
            0,
            0,
            this.canvas.width,
            this.canvas.height
        );
    }

    drawGrid() {
        this.ctx.strokeStyle = "#808080";
        this.ctx.lineWidth = 1;
        this.ctx.beginPath();

        for (let x = 0; x <= this.image.width; x += this.gridWidth) {
            let xx = x * this.zoom + 0.5;
            this.ctx.moveTo(xx, 0);
            this.ctx.lineTo(xx, this.canvas.height);
        }

        for (let y = 0; y <= this.image.height; y += this.gridHeight) {
            let yy = y * this.zoom + 0.5;
            this.ctx.moveTo(0, yy);
            this.ctx.lineTo(this.canvas.width, yy);
        }

        this.ctx.stroke();
    }

    drawSelection() {
        if (this.selectedCol < 0)
            return;

        this.ctx.strokeStyle = "#ff0000";
        this.ctx.lineWidth = 2;
        this.ctx.strokeRect(
            Math.floor(this.selectedX / this.gridWidth) * this.gridWidth * this.zoom,
            Math.floor(this.selectedY / this.gridHeight) * this.gridHeight * this.zoom,
            this.gridWidth * this.zoom,
            this.gridHeight * this.zoom
        );
    }

    canvasToTile(x, y) {
        return {
            x: Math.floor(x / this.zoom),
            y: Math.floor(y / this.zoom),
        };
    }

    installEvents() {
        this.controller = new AbortController();
        const { signal } = this.controller;

        this.canvas.addEventListener("click", e => {
            const rect = this.canvas.getBoundingClientRect();
            const event = {
                button: e.button,
                ...this.canvasToTile(
                    e.clientX - rect.left,
                    e.clientY - rect.top
            )};
            emitEvent("tile_clicked", event);
        }, { signal });

        this.canvas.addEventListener("contextmenu", e => {
            const rect = this.canvas.getBoundingClientRect();
            const event = {
                button: e.button,
                ...this.canvasToTile(
                    e.clientX - rect.left,
                    e.clientY - rect.top
            )};
            emitEvent("tile_clicked", event);
	}, { signal });
    }

    removeEvents() {
        if (this.controller) {
            this.controller.abort();
            this.controller = null;
        }
    }
}

window.tileViewer = new TileViewer();
