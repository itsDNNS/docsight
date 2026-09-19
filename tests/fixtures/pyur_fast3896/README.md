# PYUR FAST3896-15 channel fixture

`connection.json` contains only allowlisted DOCSIS numeric/unit/modulation
fields from an examined `FAST3896-15_PYUR-RDK_83.2.4` connection response:
20 downstream 256-QAM channels, one OFDM channel, five upstream QAM channels,
and 21 separate error-counter rows. It contains no authentication, session,
device identifiers, subscriber addresses or wireless configuration.

`id` joins counter rows to downstream rows; `ChannelID` is channel identity.
Tests permute the counter order and exercise missing and duplicate join IDs.
All auth/session/device test inputs elsewhere are synthetic. The original
HAR and frontend source are intentionally not included. Automated tests do
not establish hardware compatibility; reporter validation is pending.
