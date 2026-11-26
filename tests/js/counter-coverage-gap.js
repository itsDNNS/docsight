'use strict';

// One channel's uncorrectable counter (1500) is missing for one poll next to a
// channel that reports 0, then returns unchanged; afterwards it really grows by 10.
// Later one poll has no counter on any channel, and the counters come back with 20 more.
module.exports = [
    {timestamp: '2026-10-07T08:05:00Z', ds_uncorrectable_errors: 1500, ds_uncorrectable_channels: 2},
    {timestamp: '2026-10-07T09:05:00Z', ds_uncorrectable_errors: 0, ds_uncorrectable_channels: 1},
    {timestamp: '2026-10-07T10:05:00Z', ds_uncorrectable_errors: 1500, ds_uncorrectable_channels: 2},
    {timestamp: '2026-10-07T11:05:00Z', ds_uncorrectable_errors: 1510, ds_uncorrectable_channels: 2},
    {timestamp: '2026-10-07T12:05:00Z', ds_uncorrectable_errors: null, ds_uncorrectable_channels: 0},
    {timestamp: '2026-10-07T13:05:00Z', ds_uncorrectable_errors: 1530, ds_uncorrectable_channels: 2},
    {timestamp: '2026-10-07T14:05:00Z', ds_uncorrectable_errors: 1540, ds_uncorrectable_channels: 2},
];
