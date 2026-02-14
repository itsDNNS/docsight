/**
 * Hero Trend Chart - Phase 3 Task 3.1
 * 
 * Displays inline SNR + Power trend in the hero card
 * Dual Y-axis chart with 24h history
 */
(function() {
    'use strict';
    console.log('[HeroChart] Script loaded, initializing...');

    function initHeroChart() {
        console.log('[HeroChart] initHeroChart() called');
        const ctx = document.getElementById('hero-trend-chart');
        if (!ctx) {
            console.warn('[HeroChart] Canvas element #hero-trend-chart not found');
            return;
        }

        // Fetch trend data (all snapshots, will filter to 24h)
        fetch('/api/trends')
            .then(r => {
                if (!r.ok) throw new Error(`API error: ${r.status}`);
                return r.json();
            })
            .then(data => {
                if (!data || !Array.isArray(data) || data.length === 0) {
                    console.warn('[HeroChart] No trend data available');
                    renderEmptyChart(ctx);
                    return;
                }

                // Filter to last 24h
                const now = new Date();
                const twentyFourHoursAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
                const filtered = data.filter(d => {
                    const ts = new Date(d.timestamp);
                    return ts >= twentyFourHoursAgo;
                });

                if (filtered.length === 0) {
                    console.warn('[HeroChart] No data in last 24h');
                    renderEmptyChart(ctx);
                    return;
                }

                renderChart(ctx, filtered);
            })
            .catch(err => {
                console.error('[HeroChart] Failed to load data:', err);
                renderEmptyChart(ctx);
            });
    }

    function renderChart(ctx, data) {
        // Prepare datasets
        const labels = data.map(d => new Date(d.timestamp * 1000));
        const dsPower = data.map(d => d.ds_power_avg);
        const snr = data.map(d => d.ds_snr_avg);

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'DS Power (dBmV)',
                    data: dsPower,
                    borderColor: 'rgba(168,85,247,0.9)',
                    backgroundColor: 'rgba(168,85,247,0.15)',
                    yAxisID: 'y-power',
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                    fill: true
                }, {
                    label: 'SNR (dB)',
                    data: snr,
                    borderColor: 'rgba(59,130,246,0.9)',
                    backgroundColor: 'rgba(59,130,246,0.15)',
                    yAxisID: 'y-snr',
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { 
                    mode: 'index', 
                    intersect: false 
                },
                plugins: {
                    legend: { 
                        display: true, 
                        position: 'top',
                        labels: {
                            color: 'rgba(224,224,224,0.9)',
                            font: { size: 11 },
                            padding: 12,
                            usePointStyle: true
                        }
                    },
                    tooltip: { 
                        mode: 'index',
                        backgroundColor: 'rgba(15,20,25,0.95)',
                        titleColor: 'rgba(224,224,224,0.9)',
                        bodyColor: 'rgba(224,224,224,0.8)',
                        borderColor: 'rgba(168,85,247,0.3)',
                        borderWidth: 1,
                        padding: 12,
                        displayColors: true,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                label += context.parsed.y.toFixed(1);
                                if (context.dataset.yAxisID === 'y-power') {
                                    label += ' dBmV';
                                } else {
                                    label += ' dB';
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { 
                            unit: 'hour', 
                            displayFormats: { hour: 'HH:mm' },
                            tooltipFormat: 'dd.MM HH:mm'
                        },
                        grid: { 
                            color: 'rgba(255,255,255,0.05)',
                            drawBorder: false
                        },
                        ticks: {
                            color: 'rgba(224,224,224,0.6)',
                            font: { size: 10 }
                        }
                    },
                    'y-power': {
                        type: 'linear',
                        position: 'left',
                        min: -15,
                        max: 25,
                        title: { 
                            display: true, 
                            text: 'Power (dBmV)',
                            color: 'rgba(168,85,247,0.9)',
                            font: { size: 11, weight: 'bold' }
                        },
                        grid: { 
                            color: 'rgba(255,255,255,0.05)',
                            drawBorder: false
                        },
                        ticks: {
                            color: 'rgba(224,224,224,0.6)',
                            font: { size: 10 }
                        }
                    },
                    'y-snr': {
                        type: 'linear',
                        position: 'right',
                        min: 10,
                        max: 50,
                        title: { 
                            display: true, 
                            text: 'SNR (dB)',
                            color: 'rgba(59,130,246,0.9)',
                            font: { size: 11, weight: 'bold' }
                        },
                        grid: { 
                            display: false
                        },
                        ticks: {
                            color: 'rgba(224,224,224,0.6)',
                            font: { size: 10 }
                        }
                    }
                }
            }
        });
    }

    function renderEmptyChart(ctx) {
        // Render placeholder when no data available
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false }
                },
                scales: {
                    x: { display: false },
                    y: { display: false }
                }
            }
        });
        
        // Show placeholder text
        const container = ctx.parentElement;
        const placeholder = document.createElement('div');
        placeholder.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:rgba(224,224,224,0.5);font-size:13px;text-align:center;';
        placeholder.textContent = 'Keine Verlaufsdaten verfügbar';
        container.style.position = 'relative';
        container.appendChild(placeholder);
    }
    
    // Initialize immediately when script loads
    initHeroChart();
})();
