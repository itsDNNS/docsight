/* German TKG compensation wizard. All app-owned URLs use docsightUrl(). */
(function() {
    'use strict';

    var state = { initialized: false, step: 1, claimId: null, calculation: null, proposals: [], origin: 'manual', customerDefaults: {}, localToday: '' };

    function t(key, fallback) {
        return (window.T && window.T['docsight.de_tkg_compensation.' + key]) || fallback;
    }

    function status(message, kind) {
        var node = document.getElementById('tkg-status');
        if (!node) return;
        node.textContent = message || '';
        node.dataset.kind = kind || 'info';
    }

    function renderEmptyDerivedState() {
        var calculation = document.getElementById('tkg-calculation');
        calculation.replaceChildren();
        var empty = document.createElement('p');
        empty.className = 'tkg-muted';
        empty.textContent = t('calculation_empty', 'Confirm and calculate the facts first.');
        calculation.append(empty);
        document.getElementById('tkg-report-links').replaceChildren();
    }

    function invalidateDerivedState() {
        state.calculation = null;
        renderEmptyDerivedState();
        document.getElementById('tkg-letter').value = '';
        status(t('status_stale', 'Facts changed. Recalculate and regenerate the letter.'), 'info');
    }

    function invalidateLetter() {
        if (document.getElementById('tkg-letter').value) {
            document.getElementById('tkg-letter').value = '';
            status(t('status_letter_stale', 'Letter details changed. Generate the letter again.'), 'info');
        }
    }

    function api(path, options) {
        var init = options || {};
        init.headers = Object.assign({'Content-Type': 'application/json'}, init.headers || {});
        return fetch(window.docsightUrl(path), init).then(function(response) {
            return response.json().catch(function() { return {}; }).then(function(payload) {
                if (!response.ok) {
                    var error = new Error(payload.error || t('status_error', 'The request could not be completed.'));
                    error.code = payload.code;
                    throw error;
                }
                return payload;
            });
        });
    }

    function showStep(number) {
        state.step = Math.max(1, Math.min(5, number));
        document.querySelectorAll('#tkg-compensation-root [data-tkg-step]').forEach(function(panel) {
            panel.hidden = Number(panel.dataset.tkgStep) !== state.step;
        });
        document.querySelectorAll('#tkg-compensation-root [data-tkg-step-indicator]').forEach(function(item) {
            if (Number(item.dataset.tkgStepIndicator) === state.step) item.setAttribute('aria-current', 'step');
            else item.removeAttribute('aria-current');
        });
        document.getElementById('tkg-previous').disabled = state.step === 1;
        document.getElementById('tkg-next').hidden = state.step === 5;
        var active = document.querySelector('#tkg-compensation-root [data-tkg-step="' + state.step + '"]');
        if (active) active.focus({preventScroll: true});
    }

    function centsFromInput(id, required) {
        var value = document.getElementById(id).value.trim();
        if (!value && !required) return null;
        if (!/^\d+(?:\.\d{0,2})?$/.test(value)) return null;
        var parts = value.split('.');
        return Number(parts[0]) * 100 + Number((parts[1] || '').padEnd(2, '0'));
    }

    function dateRange(startValue, endValue) {
        if (!startValue || !endValue || endValue < startValue) return [];
        var result = [];
        var cursor = new Date(startValue + 'T00:00:00Z');
        var end = new Date(endValue + 'T00:00:00Z');
        while (cursor <= end) {
            result.push(cursor.toISOString().slice(0, 10));
            cursor.setUTCDate(cursor.getUTCDate() + 1);
        }
        return result;
    }

    function renderDays() {
        var container = document.getElementById('tkg-days');
        var previous = {};
        container.querySelectorAll('.tkg-day').forEach(function(row) {
            previous[row.dataset.date] = {
                complete: row.querySelector('[data-kind="complete"]').checked,
                replacement: row.querySelector('[data-kind="replacement"]').checked
            };
        });
        container.replaceChildren();
        var start = document.getElementById('tkg-report-date').value;
        var end = document.getElementById('tkg-restored-date').value || state.localToday;
        var days = start ? dateRange(start, end) : [];
        state.proposals.forEach(function(day) {
            if (days.indexOf(day) === -1) days.push(day);
        });
        days.sort().forEach(function(day) {
            var row = document.createElement('div');
            row.className = 'tkg-day';
            row.dataset.date = day;
            var dayLabel = document.createElement('strong');
            dayLabel.textContent = day;
            var completeLabel = document.createElement('label');
            var complete = document.createElement('input');
            complete.type = 'checkbox';
            complete.dataset.tkgFact = '';
            complete.dataset.kind = 'complete';
            complete.checked = Boolean(previous[day] && previous[day].complete);
            completeLabel.append(complete, document.createTextNode(' ' + t('day_complete', 'Complete outage')));
            var replacementLabel = document.createElement('label');
            var replacement = document.createElement('input');
            replacement.type = 'checkbox';
            replacement.dataset.tkgFact = '';
            replacement.dataset.kind = 'replacement';
            replacement.checked = Boolean(previous[day] && previous[day].replacement);
            replacement.addEventListener('change', function() {
                if (replacement.checked) complete.checked = true;
                invalidateDerivedState();
            });
            complete.addEventListener('change', function() {
                if (!complete.checked) replacement.checked = false;
                invalidateDerivedState();
            });
            replacementLabel.append(replacement, document.createTextNode(' ' + t('day_replacement', 'Provider replacement solution actually made available')));
            if (state.proposals.indexOf(day) !== -1) {
                var badge = document.createElement('span');
                badge.className = 'tkg-badge';
                badge.textContent = t('candidate_derived', 'Derived proposal · not confirmed');
                dayLabel.append(document.createTextNode(' '), badge);
            }
            row.append(dayLabel, completeLabel, replacementLabel);
            container.append(row);
        });
    }

    function applyCandidate(candidate) {
        document.getElementById('tkg-window-from').value = candidate.window_from_local;
        document.getElementById('tkg-window-to').value = candidate.window_to_local;
        document.getElementById('tkg-report-date').value = '';
        document.getElementById('tkg-restored-date').value = '';
        state.proposals = candidate.suggested_days || [];
        state.origin = candidate.origin || 'manual';
        invalidateDerivedState();
        renderDays();
        if (candidate.ongoing) {
            status(t('candidate_ongoing', 'Ongoing proposal through the latest available evidence; no restoration is inferred.'));
        }
        showStep(2);
    }

    function renderCandidates(payload) {
        var container = document.getElementById('tkg-candidates');
        container.replaceChildren();
        state.customerDefaults = payload.customer_defaults || {};
        state.localToday = payload.local_today || '';
        document.getElementById('tkg-customer-name').value = state.customerDefaults.name || '';
        document.getElementById('tkg-customer-number').value = state.customerDefaults.customer_number || '';
        document.getElementById('tkg-customer-address').value = state.customerDefaults.address || '';
        var performanceLink = document.getElementById('tkg-performance-link');
        if (payload.capabilities.bnetz) {
            performanceLink.removeAttribute('target');
            performanceLink.onclick = function(event) {
                event.preventDefault();
                if (typeof window.switchView === 'function') window.switchView('bnetz');
            };
        }
        if (!payload.candidates.length) {
            var empty = document.createElement('p');
            empty.className = 'tkg-muted';
            empty.textContent = t('candidate_empty', 'No supporting proposal is available. Enter the window manually.');
            container.append(empty);
            return;
        }
        payload.candidates.forEach(function(candidate) {
            var row = document.createElement('div');
            row.className = 'tkg-candidate';
            var text = document.createElement('span');
            text.textContent = (candidate.label || candidate.window_from + ' – ' + candidate.window_to) + ' · ' + t('candidate_derived', 'Derived proposal · not confirmed');
            var use = document.createElement('button');
            use.className = 'btn';
            use.type = 'button';
            use.textContent = t('candidate_use', 'Use proposal');
            use.setAttribute('aria-label', t('candidate_use', 'Use proposal') + ': ' + (candidate.label || candidate.window_from + ' – ' + candidate.window_to));
            use.addEventListener('click', function() { applyCandidate(candidate); });
            row.append(text, use);
            container.append(row);
        });
    }

    function loadCandidates() {
        status(t('status_loading', 'Loading…'));
        api('/api/de-tkg/candidates').then(function(payload) {
            renderCandidates(payload);
            status('');
        }).catch(function(error) { status(error.message, 'error'); });
    }

    function selectedDays(kind) {
        return Array.from(document.querySelectorAll('#tkg-days .tkg-day')).filter(function(row) {
            return row.querySelector('[data-kind="' + kind + '"]').checked;
        }).map(function(row) { return row.dataset.date; });
    }

    function claimPayload() {
        var fee = centsFromInput('tkg-monthly-fee', true);
        var credit = centsFromInput('tkg-prior-credit', false);
        return {
            status: 'draft',
            origin: state.origin,
            window_from: document.getElementById('tkg-window-from').value || null,
            window_to: document.getElementById('tkg-window-to').value || null,
            fault_report_received_date: document.getElementById('tkg-report-date').value || null,
            fault_report_channel: document.getElementById('tkg-report-channel').value,
            ticket_ref: document.getElementById('tkg-ticket-ref').value,
            restored_date: document.getElementById('tkg-restored-date').value || null,
            monthly_fee_cents: fee,
            confirmed_days: selectedDays('complete'),
            eligibility: {
                complete_outage: document.getElementById('tkg-complete-outage').checked,
                replacement_solution_days: selectedDays('replacement'),
                user_responsibility: document.getElementById('tkg-user-responsibility').checked,
                force_majeure: document.getElementById('tkg-force-majeure').checked,
                lawful_interruption: document.getElementById('tkg-lawful-interruption').checked,
                missed_appointments: Number(document.getElementById('tkg-missed-appointments').value || 0)
            },
            prior_credit: credit == null ? {} : {
                amount_cents: credit,
                classification: document.getElementById('tkg-credit-classification').value
            }
        };
    }

    function factsValid() {
        var fee = centsFromInput('tkg-monthly-fee', true);
        var outage = document.getElementById('tkg-complete-outage').checked;
        var appointments = Number(document.getElementById('tkg-missed-appointments').value || 0);
        if (fee === null || !Number.isInteger(appointments) || appointments < 0 || appointments > 100) return false;
        if (!outage) return appointments > 0;
        return Boolean(
            document.getElementById('tkg-window-from').value &&
            document.getElementById('tkg-window-to').value &&
            document.getElementById('tkg-report-date').value &&
            selectedDays('complete').length > 0
        );
    }

    function euros(cents) { return (Number(cents || 0) / 100).toFixed(2).replace('.', ',') + ' €'; }

    function renderCalculation(result) {
        state.calculation = result;
        var container = document.getElementById('tkg-calculation');
        container.replaceChildren();
        var summary = document.createElement('div');
        summary.className = 'tkg-summary';
        [
            [t('total_outage', 'Complete-outage total'), result.total_cents],
            [t('total_appointments', 'Missed-appointment total'), result.missed_appointments_total_cents],
            [t('grand_total', 'Prospective total'), result.grand_total_cents]
        ].forEach(function(item) {
            var card = document.createElement('div');
            var label = document.createElement('div'); label.className = 'tkg-muted'; label.textContent = item[0];
            var value = document.createElement('strong'); value.textContent = euros(item[1]);
            card.append(label, value); summary.append(card);
        });
        container.append(summary);
        if (result.days.length || result.exclusions.length) {
            var table = document.createElement('table'); table.className = 'tkg-table';
            var head = document.createElement('thead');
            var headingRow = document.createElement('tr');
            [
                t('column_date', 'Date'), t('column_day', 'Day'), t('column_basis', 'Basis'),
                t('column_amount', 'Amount'), t('column_rule', 'Rule')
            ].forEach(function(labelText) {
                var heading = document.createElement('th'); heading.scope = 'col'; heading.textContent = labelText; headingRow.append(heading);
            });
            head.append(headingRow);
            var body = document.createElement('tbody');
            result.days.forEach(function(day) {
                var row = document.createElement('tr');
                var basis = t(day.basis === 'percent' ? 'basis_percent' : 'basis_flat', day.basis) +
                    ' · max(' + euros(day.flat_cents) + '; ' + day.percentage + '% = ' + euros(day.percentage_cents) + ')';
                [day.date, String(day.day_index), basis, euros(day.amount_cents), day.rule_ref].forEach(function(value) {
                    var cell = document.createElement('td'); cell.textContent = value; row.append(cell);
                });
                body.append(row);
            });
            table.append(head, body); container.append(table);
        }
        if (result.exclusions.length) {
            var excludedHeading = document.createElement('h4'); excludedHeading.textContent = t('excluded_days', 'Excluded confirmed days'); container.append(excludedHeading);
            var excludedList = document.createElement('ul');
            result.exclusions.forEach(function(exclusion) {
                var item = document.createElement('li');
                item.textContent = exclusion.date + ' · ' + (
                    exclusion.reason === 'statutory_waiting_period'
                        ? t('waiting_period', 'The report-receipt date is day 0; no TKG §58(3) entitlement is calculated before the third calendar day after receipt.')
                        : t('replacement_help', exclusion.explanation)
                );
                excludedList.append(item);
            });
            container.append(excludedList);
        }
        var metadata = document.createElement('p');
        metadata.textContent = t('rule_version', 'Rules version') + ': ' + result.rules_version + ' · ' + t('effective_date', 'Effective date') + ': ' + result.effective_date;
        container.append(metadata);
        if (result.rounding_note) {
            var rounding = document.createElement('p'); rounding.className = 'tkg-callout'; rounding.textContent = t('rounding_note', result.rounding_note); container.append(rounding);
        }
        if (result.missed_appointments.length) {
            var appointmentsHeading = document.createElement('h4'); appointmentsHeading.textContent = t('missed_appointments', 'Missed service/installation appointments'); container.append(appointmentsHeading);
            var appointmentsList = document.createElement('ul');
            result.missed_appointments.forEach(function(appointment, index) {
                var item = document.createElement('li');
                item.textContent = String(index + 1) + ' · max(' + euros(appointment.flat_cents) + '; ' + appointment.percentage + '% = ' + euros(appointment.percentage_cents) + ') = ' + euros(appointment.amount_cents) + ' · ' + appointment.rule_ref;
                appointmentsList.append(item);
            });
            container.append(appointmentsList);
        }
        var credit = document.createElement('p');
        credit.textContent = t('credit_separate', 'A prior credit is shown separately and is never deducted automatically.');
        if (result.prior_credit.amount_cents != null) {
            var creditLabels = {
                goodwill: t('credit_goodwill', 'Goodwill'),
                reduction: t('credit_reduction', 'Fee reduction'),
                compensation: t('credit_compensation', 'Compensation'),
                unclear: t('credit_unclear', 'Unclear')
            };
            credit.textContent += ' ' + euros(result.prior_credit.amount_cents) + ' · ' + (creditLabels[result.prior_credit.classification] || creditLabels.unclear);
        }
        container.append(credit);
        var sourceHeading = document.createElement('h4'); sourceHeading.textContent = t('sources', 'Rules and sources'); container.append(sourceHeading);
        var sourceList = document.createElement('ul');
        result.sources.forEach(function(source) {
            var item = document.createElement('li');
            var link = document.createElement('a'); link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = source.label;
            item.append(link); sourceList.append(item);
        });
        container.append(sourceList);
        var review = document.createElement('p'); review.className = 'tkg-muted'; review.textContent = t('rounding_note', result.source_review_note) + ' ' + t('replacement_help', 'A confirmed replacement solution excludes only that day conservatively. Acceptance or suitability is not inferred.'); container.append(review);
        renderReportLinks(result);
    }

    function renderReportLinks(result) {
        var container = document.getElementById('tkg-report-links');
        container.replaceChildren();
        if (!result || !result.report_chunks || !result.report_chunks.length) {
            var unavailable = document.createElement('p'); unavailable.textContent = t('no_reports', 'The Reports module is unavailable. Copy and .txt export remain available.'); container.append(unavailable);
        } else {
            var heading = document.createElement('h4'); heading.textContent = t('report_attachments', 'Evidence report attachments'); container.append(heading);
            result.report_chunks.forEach(function(chunk) {
                var link = document.createElement('a'); link.href = window.docsightUrl(chunk.url); link.textContent = t('report_attachments', 'Evidence report attachments') + ' ' + chunk.index; container.append(link);
            });
            if (result.report_chunks.length > 1) {
                var note = document.createElement('p'); note.className = 'tkg-callout'; note.textContent = t('report_chunk_note', 'The 90-day split is a technical PDF limit, not a limit on the claim period.'); container.append(note);
            }
        }
        if (result && result.evidence_checklist_url) {
            var checklist = document.createElement('a'); checklist.href = window.docsightUrl(result.evidence_checklist_url); checklist.textContent = t('evidence_checklist', 'Evidence checklist'); container.append(checklist);
        }
        if (result && result.journal_export_url) {
            var journal = document.createElement('a'); journal.href = window.docsightUrl(result.journal_export_url); journal.textContent = (window.T && window.T.export_journal) || 'Incident journal export'; container.append(journal);
        }
    }

    function calculate() {
        if (!factsValid()) { status(t('validation_facts', 'Enter the fee and either confirm the outage facts or at least one missed appointment.'), 'error'); return; }
        var payload = claimPayload();
        var path = state.claimId ? '/api/de-tkg/claims/' + state.claimId : '/api/de-tkg/claims';
        var method = state.claimId ? 'PUT' : 'POST';
        status(t('status_loading', 'Loading…'));
        api(path, {method: method, body: JSON.stringify(payload)}).then(function(claim) {
            state.claimId = claim.id;
            return api('/api/de-tkg/claims/' + claim.id + '/calculate', {method: 'POST', body: '{}'});
        }).then(function(result) {
            renderCalculation(result); status(t('status_calculated', 'Calculation updated.')); showStep(3);
        }).catch(function(error) { status(error.message, 'error'); });
    }

    function generateLetter() {
        if (!state.claimId || !state.calculation) { status(t('calculation_empty', 'Confirm and calculate the facts first.'), 'error'); return; }
        var customer = {
            name: document.getElementById('tkg-customer-name').value,
            customer_number: document.getElementById('tkg-customer-number').value,
            address: document.getElementById('tkg-customer-address').value
        };
        api('/api/de-tkg/claims/' + state.claimId + '/letter', {method: 'POST', body: JSON.stringify({customer: customer})}).then(function(result) {
            document.getElementById('tkg-letter').value = result.letter_text;
            status(t('status_letter', 'German letter generated. Review and edit it.'));
        }).catch(function(error) { status(error.message, 'error'); });
    }

    function saveEditedLetter() {
        if (!state.claimId) return Promise.reject(new Error(t('calculation_empty', 'Confirm and calculate the facts first.')));
        return api('/api/de-tkg/claims/' + state.claimId, {method: 'PUT', body: JSON.stringify({letter_text: document.getElementById('tkg-letter').value})});
    }

    function copyLetter() {
        var text = document.getElementById('tkg-letter').value;
        if (!text) { status(t('letter_placeholder', 'Generate the letter after reviewing the calculation.'), 'error'); return; }
        function fallbackCopy() {
            var active = document.activeElement;
            var textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.append(textarea);
            textarea.focus();
            textarea.select();
            textarea.setSelectionRange(0, textarea.value.length);
            var copied = false;
            try { copied = document.execCommand('copy'); } catch (_error) { copied = false; }
            textarea.remove();
            if (active && typeof active.focus === 'function') active.focus();
            if (copied) status(t('status_copied', 'Letter copied.'));
            else status(t('status_copy_failed', 'The letter could not be copied. Select the text and copy it manually.'), 'error');
        }
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            navigator.clipboard.writeText(text).then(function() {
                status(t('status_copied', 'Letter copied.'));
            }).catch(fallbackCopy);
        } else {
            fallbackCopy();
        }
    }

    function downloadLetter() {
        if (!document.getElementById('tkg-letter').value) { status(t('letter_placeholder', 'Generate the letter after reviewing the calculation.'), 'error'); return; }
        saveEditedLetter().then(function() {
            var link = document.createElement('a');
            link.href = window.docsightUrl('/api/de-tkg/claims/' + state.claimId + '/letter?download=1');
            link.download = '';
            document.body.append(link);
            link.click();
            link.remove();
        }).catch(function(error) { status(error.message, 'error'); });
    }

    function completeClaim() {
        if (!state.claimId) return;
        saveEditedLetter().then(function() {
            return api('/api/de-tkg/claims/' + state.claimId, {method: 'PUT', body: JSON.stringify({status: 'completed'})});
        }).then(function() { status(t('status_completed', 'Draft marked completed.')); }).catch(function(error) { status(error.message, 'error'); });
    }

    function next() {
        if (state.step === 1) {
            var from = document.getElementById('tkg-window-from').value;
            var to = document.getElementById('tkg-window-to').value;
            if (Boolean(from) !== Boolean(to)) { status(t('validation_window', 'Enter both window bounds or leave both blank for an appointment-only claim.'), 'error'); return; }
            renderDays();
        } else if (state.step === 2 && !state.calculation) {
            status(t('calculation_empty', 'Confirm and calculate the facts first.'), 'error'); return;
        } else if (state.step === 4 && !document.getElementById('tkg-letter').value) {
            status(t('letter_placeholder', 'Generate the letter after reviewing the calculation.'), 'error'); return;
        }
        showStep(state.step + 1);
    }

    function initDeTkgCompensation() {
        if (state.initialized) return;
        state.initialized = true;
        document.getElementById('tkg-load-candidates').addEventListener('click', loadCandidates);
        document.getElementById('tkg-calculate').addEventListener('click', calculate);
        document.getElementById('tkg-generate-letter').addEventListener('click', generateLetter);
        document.getElementById('tkg-copy').addEventListener('click', copyLetter);
        document.getElementById('tkg-download').addEventListener('click', downloadLetter);
        document.getElementById('tkg-complete').addEventListener('click', completeClaim);
        document.getElementById('tkg-previous').addEventListener('click', function() { showStep(state.step - 1); });
        document.getElementById('tkg-next').addEventListener('click', next);
        ['tkg-report-date', 'tkg-restored-date'].forEach(function(id) { document.getElementById(id).addEventListener('change', renderDays); });
        document.querySelectorAll('#tkg-compensation-root [data-tkg-fact]').forEach(function(element) {
            element.addEventListener(element.type === 'checkbox' || element.tagName === 'SELECT' ? 'change' : 'input', invalidateDerivedState);
        });
        ['tkg-window-from', 'tkg-window-to'].forEach(function(id) {
            document.getElementById(id).addEventListener('input', function() {
                state.proposals = [];
                state.origin = 'manual';
            });
        });
        ['tkg-customer-name', 'tkg-customer-number', 'tkg-customer-address'].forEach(function(id) {
            document.getElementById(id).addEventListener('input', invalidateLetter);
        });
        document.getElementById('tkg-monthly-fee').addEventListener('input', function(event) { document.getElementById('tkg-zero-fee').hidden = event.target.value !== '0' && event.target.value !== '0.00'; });
        showStep(1);
        loadCandidates();
    }

    window.initDeTkgCompensation = initDeTkgCompensation;
    window.initDe_tkg_compensation = initDeTkgCompensation;
})();
