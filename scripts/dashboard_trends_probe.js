/* Browser-only measurement instrumentation, installed before production scripts.
 * Requires a real uPlot draw, signal values, and colored curve pixels inside the
 * plotting area. Axes, blank canvases, and translucent area fills do not qualify.
 */
(() => {
    const probe = window.dashboardTrendsProbe = {paints: [], charts: [], activeObservers: 0};
    const Observer = window.ResizeObserver;
    window.ResizeObserver = class extends Observer {
        constructor(callback) { super(callback); this.active = false; }
        observe(...args) {
            if (!this.active) { probe.activeObservers++; this.active = true; }
            return super.observe(...args);
        }
        disconnect() {
            if (this.active) { probe.activeObservers--; this.active = false; }
            return super.disconnect();
        }
    };
    let uplot;
    Object.defineProperty(window, 'uPlot', {
        configurable: true,
        get: () => uplot,
        set: Original => {
            uplot = new Proxy(Original, {construct(Target, args) {
                const [opts, data, container] = args;
                if (container && container.id === 'hero-trend-chart') {
                    opts.hooks = opts.hooks || {};
                    const record = {data, destroyed: false};
                    probe.charts.push(record);
                    (opts.hooks.destroy = opts.hooks.destroy || []).push(() => { record.destroyed = true; });
                    (opts.hooks.draw = opts.hooks.draw || []).push(u => {
                        if (!u.data.slice(1).some(values => values.filter(v => v != null).length >= 2)) return;
                        const b = u.bbox;
                        if (b.width < 8 || b.height < 8) return;
                        const pixels = u.ctx.getImageData(b.left + 3, b.top + 3, b.width - 6, b.height - 6).data;
                        let colored = 0;
                        for (let i = 0; i < pixels.length; i += 4) {
                            const [r, g, blue, alpha] = pixels.subarray(i, i + 4);
                            if (alpha > 180 && ((r > 130 && r < 200 && g < 130 && blue > 180) ||
                                (r > 210 && g > 100 && g < 200 && blue < 100) ||
                                (r < 100 && g > 80 && g < 180 && blue > 180))) colored++;
                        }
                        if (colored < 20) return;
                        // This frame callback runs after the completed canvas draw.
                        requestAnimationFrame(() => {
                            if (u.root.isConnected && !record.destroyed) {
                                probe.paints.push({time: performance.now(), coloredPixels: colored,
                                    points: u.data[0].length, first: u.data[1][0]});
                            }
                        });
                    });
                }
                return Reflect.construct(Target, args);
            }});
        }
    });
})();
