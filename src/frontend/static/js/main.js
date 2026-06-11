/**
 * Health Advisor — Site-wide JavaScript
 * All IIFEs, no ES modules. Runs in Flask static context.
 */

/* ============================================================
   1. DARK MODE
   Runs outside DOMContentLoaded so it applies before paint.
   ============================================================ */
(function DarkMode() {
    var root = document.documentElement;
    var btn;

    function apply(dark) {
        root.setAttribute('data-theme', dark ? 'dark' : 'light');
        if (!btn) btn = document.getElementById('darkModeToggle');
        if (btn) {
            btn.innerHTML = dark
                ? '<i class="fas fa-sun" aria-hidden="true"></i>'
                : '<i class="fas fa-moon" aria-hidden="true"></i>';
            btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
        }
    }

    // Apply on load (inline script in <head> already sets the attribute,
    // but we need to sync the button icon once the DOM is ready)
    var saved = localStorage.getItem('theme');
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    apply(saved ? saved === 'dark' : prefersDark);

    document.addEventListener('DOMContentLoaded', function () {
        btn = document.getElementById('darkModeToggle');
        // Re-apply to sync icon now that DOM is ready
        apply(root.getAttribute('data-theme') === 'dark');

        if (btn) {
            btn.addEventListener('click', function () {
                var next = root.getAttribute('data-theme') !== 'dark';
                localStorage.setItem('theme', next ? 'dark' : 'light');
                apply(next);
            });
        }
    });
})();


document.addEventListener('DOMContentLoaded', function () {

    /* ============================================================
       2. NAVBAR HAMBURGER
       ============================================================ */
    (function Navbar() {
        var hamburger = document.getElementById('navbarToggle');
        var menu = document.getElementById('navbarMenu');
        if (!hamburger || !menu) return;

        hamburger.addEventListener('click', function () {
            var expanded = hamburger.getAttribute('aria-expanded') === 'true';
            hamburger.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            hamburger.classList.toggle('active');
            menu.classList.toggle('active');
        });

        // Close when any nav link is clicked (mobile)
        menu.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                hamburger.classList.remove('active');
                menu.classList.remove('active');
                hamburger.setAttribute('aria-expanded', 'false');
            });
        });

        // Close on outside click
        document.addEventListener('click', function (e) {
            if (!hamburger.contains(e.target) && !menu.contains(e.target)) {
                hamburger.classList.remove('active');
                menu.classList.remove('active');
                hamburger.setAttribute('aria-expanded', 'false');
            }
        });
    })();


    /* ============================================================
       3. LOADING OVERLAY
       Shows while the /analyze form is submitting.
       ============================================================ */
    (function LoadingOverlay() {
        var form = document.getElementById('analyzeForm') || document.querySelector('form[action="/analyze"]');
        var overlay = document.getElementById('loadingOverlay');
        if (!form || !overlay) return;

        form.addEventListener('submit', function () {
            var symptoms = form.querySelector('#symptoms');
            if (!symptoms || !symptoms.value.trim()) return;

            // Store severity for results page to read
            var severityInput = document.getElementById('severityInput');
            if (severityInput && severityInput.value) {
                sessionStorage.setItem('lastSeverity', severityInput.value);
            } else {
                sessionStorage.removeItem('lastSeverity');
            }

            overlay.classList.add('active');

            // Safety timeout: remove overlay after 45 seconds
            setTimeout(function () {
                overlay.classList.remove('active');
            }, 45000);
        });

        // Remove overlay when navigating away (e.g. browser back)
        window.addEventListener('pageshow', function (e) {
            if (e.persisted) overlay.classList.remove('active');
        });
    })();


    /* ============================================================
       4. SYMPTOM AUTOCOMPLETE
       Real-time suggestions from /api/symptoms?q=
       ============================================================ */
    (function SymptomAutocomplete() {
        var textarea = document.getElementById('symptoms');
        if (!textarea) return;

        var dropdown = document.createElement('div');
        dropdown.className = 'shadow-lg rounded-lg overflow-hidden';
        dropdown.setAttribute('role', 'listbox');
        dropdown.setAttribute('aria-label', 'Symptom suggestions');
        dropdown.style.cssText = [
            'position:absolute',
            'max-height:200px',
            'overflow-y:auto',
            'width:100%',
            'display:none',
            'background-color:var(--bg-secondary)',
            'border:1px solid var(--border-color)',
            'z-index:20',
            'border-radius:var(--radius-md)',
            'box-shadow:var(--shadow-lg)'
        ].join(';');

        textarea.parentElement.style.position = 'relative';
        textarea.parentElement.appendChild(dropdown);

        var debounceTimer;

        textarea.addEventListener('input', function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                var text = textarea.value;
                var lastComma = text.lastIndexOf(',');
                var q = text.slice(lastComma + 1).trim();
                if (q.length < 2) { dropdown.style.display = 'none'; return; }

                fetch('/api/symptoms?q=' + encodeURIComponent(q))
                    .then(function (res) { return res.json(); })
                    .then(function (data) {
                        dropdown.innerHTML = '';
                        if (!data.symptoms || !data.symptoms.length) {
                            dropdown.style.display = 'none';
                            return;
                        }
                        data.symptoms.slice(0, 8).forEach(function (s) {
                            var btn = document.createElement('button');
                            btn.type = 'button';
                            btn.setAttribute('role', 'option');
                            btn.style.cssText = 'display:block;width:100%;padding:8px 16px;text-align:left;background:transparent;border:none;cursor:pointer;font-family:var(--font-family);font-size:0.9rem;color:var(--text-primary);transition:background 0.1s;';
                            btn.textContent = s;
                            btn.addEventListener('mouseover', function () {
                                btn.style.backgroundColor = 'var(--primary-50)';
                            });
                            btn.addEventListener('mouseout', function () {
                                btn.style.backgroundColor = 'transparent';
                            });
                            btn.addEventListener('click', function () {
                                var before = text.slice(0, lastComma + 1);
                                textarea.value = (before ? before + ' ' : '') + s + ', ';
                                dropdown.style.display = 'none';
                                textarea.focus();
                            });
                            dropdown.appendChild(btn);
                        });
                        dropdown.style.display = 'block';
                    })
                    .catch(function () {
                        dropdown.style.display = 'none';
                    });
            }, 220);
        });

        document.addEventListener('click', function (e) {
            if (textarea.parentElement && !textarea.parentElement.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });

        textarea.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') dropdown.style.display = 'none';
        });
    })();


    /* ============================================================
       5. DEMO MODE
       Pre-fills symptom textarea with example scenarios.
       ============================================================ */
    (function DemoMode() {
        var DEMO_SCENARIOS = [
            { symptoms: 'high fever, chills, sweating, muscle pain, headache', label: 'Malaria' },
            { symptoms: 'itchy rash, red bumps, inflamed skin, pus-filled spots', label: 'Acne' },
            { symptoms: 'frequent urination, excessive thirst, blurred vision, fatigue', label: 'Diabetes' },
            { symptoms: 'chest pain, shortness of breath, palpitations, dizziness', label: 'Heart Condition' },
            { symptoms: 'runny nose, sneezing, sore throat, mild cough, fatigue', label: 'Common Cold' },
        ];
        var demoIdx = 0;
        var btn = document.getElementById('demoModeBtn');
        if (!btn) return;

        btn.addEventListener('click', function () {
            var scenario = DEMO_SCENARIOS[demoIdx % DEMO_SCENARIOS.length];
            var textarea = document.getElementById('symptoms');
            if (textarea) textarea.value = scenario.symptoms;
            btn.innerHTML = '<i class="fas fa-flask mr-2" aria-hidden="true"></i>Demo: ' + scenario.label;
            demoIdx++;
        });
    })();


    /* ============================================================
       6. SEVERITY SELECTOR
       Highlights selected severity button, writes to hidden input.
       ============================================================ */
    (function SeveritySelector() {
        var options = document.querySelectorAll('.severity-option');
        var input = document.getElementById('severityInput');
        if (!options.length || !input) return;

        options.forEach(function (option) {
            option.addEventListener('click', function () {
                options.forEach(function (o) {
                    o.classList.remove('selected');
                    o.setAttribute('aria-pressed', 'false');
                });
                option.classList.add('selected');
                option.setAttribute('aria-pressed', 'true');
                input.value = option.dataset.severity;
            });
        });
    })();


    /* ============================================================
       7. EMERGENCY SYMPTOM CHECKER
       Shows a banner when high-risk symptom combinations are typed.
       Also checks symptom chips on results page.
       ============================================================ */
    (function EmergencyChecker() {
        var EMERGENCY_RULES = [
            {
                symptoms: ['chest pain', 'shortness of breath'],
                message: 'Chest pain with shortness of breath may indicate a cardiac emergency.'
            },
            {
                symptoms: ['chest pain', 'left arm pain'],
                message: 'Chest pain with arm pain may indicate a heart attack. Call 112/911 NOW.'
            },
            {
                symptoms: ['chest pain', 'sweating', 'nausea'],
                message: 'These symptoms may indicate a heart attack. Seek emergency care immediately.'
            },
            {
                symptoms: ['severe headache', 'stiff neck', 'fever'],
                message: 'Severe headache with stiff neck and fever may indicate meningitis.'
            },
            {
                symptoms: ['facial drooping', 'arm weakness', 'slurred speech'],
                message: 'These symptoms may indicate a stroke. Act FAST — call 112/911 immediately.'
            },
            {
                symptoms: ['sudden confusion', 'severe headache', 'vision loss'],
                message: 'These symptoms may indicate a stroke or serious neurological emergency.'
            },
            {
                symptoms: ['difficulty breathing', 'severe chest pain'],
                message: 'Severe breathing difficulty with chest pain requires immediate emergency care.'
            },
            {
                symptoms: ['high fever', 'rash', 'stiff neck'],
                message: 'These symptoms may indicate a serious infection such as meningitis.'
            },
        ];

        function checkText(text) {
            text = text.toLowerCase();
            for (var i = 0; i < EMERGENCY_RULES.length; i++) {
                var rule = EMERGENCY_RULES[i];
                var allMatch = rule.symptoms.every(function (s) { return text.indexOf(s) !== -1; });
                if (allMatch) return rule.message;
            }
            return null;
        }

        function showBanner(message) {
            var banner = document.getElementById('emergencyBanner');
            var bannerText = document.getElementById('emergencyBannerText');
            if (!banner) return;
            if (bannerText) bannerText.textContent = message;
            banner.style.display = 'block';
        }

        function hideBanner() {
            var banner = document.getElementById('emergencyBanner');
            if (banner) banner.style.display = 'none';
        }

        // Live check while typing (homepage)
        var textarea = document.getElementById('symptoms');
        if (textarea) {
            var debounceTimer;
            textarea.addEventListener('input', function () {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(function () {
                    var warning = document.getElementById('emergencyFormWarning');
                    var warningText = document.getElementById('emergencyFormText');
                    var msg = checkText(textarea.value);
                    if (msg) {
                        if (warningText) warningText.textContent = msg;
                        if (warning) warning.style.display = 'flex';
                        showBanner(msg);
                    } else {
                        if (warning) warning.style.display = 'none';
                        hideBanner();
                    }
                }, 400);
            });
        }

        // Check on results page using symptom chips text
        var symptomsEl = document.querySelector('.symptoms-chips');
        if (symptomsEl && !textarea) {
            var text = symptomsEl.textContent;
            var msg = checkText(text);
            if (msg) showBanner(msg);
        }
    })();


    /* ============================================================
       8. TABS (results page recommendation tabs)
       ============================================================ */
    (function Tabs() {
        var tabButtons = document.querySelectorAll('.tab-button');
        if (!tabButtons.length) return;

        tabButtons.forEach(function (button) {
            button.addEventListener('click', function () {
                var tabName = this.getAttribute('data-tab');

                tabButtons.forEach(function (btn) {
                    btn.classList.remove('active');
                    btn.setAttribute('aria-selected', 'false');
                });

                document.querySelectorAll('.tab-content-item').forEach(function (content) {
                    content.classList.remove('active');
                });

                this.classList.add('active');
                this.setAttribute('aria-selected', 'true');

                var target = document.querySelector('[data-tab-content="' + tabName + '"]');
                if (target) target.classList.add('active');
            });
        });
    })();


    /* ============================================================
       9. TREATMENT PLAN CREATION (results page)
       ============================================================ */
    (function TreatmentPlan() {
        var btn = document.getElementById('create-treatment-plan');
        if (!btn) return;

        btn.addEventListener('click', function (e) {
            e.preventDefault();
            var disease = btn.dataset.disease;
            if (!disease) return;

            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner animate-spin" aria-hidden="true"></i>&nbsp;Creating…';

            // Identity is decided server-side from the session; only the disease is sent
            var csrf = document.querySelector('meta[name="csrf-token"]');
            fetch('/create-treatment-plan', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrf ? csrf.content : '',
                },
                body: JSON.stringify({ disease: disease }),
            })
            .then(function (response) {
                if (!response.ok) throw new Error('Server returned ' + response.status);
                return response.json();
            })
            .then(function (data) {
                window.location.href = '/treatment-tracker/' + data.user_id + '/' + data.plan_id;
            })
            .catch(function () {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-notes-medical" aria-hidden="true"></i>&nbsp;Create Treatment Plan';
                var errEl = document.createElement('div');
                errEl.className = 'alert alert-danger mt-4';
                errEl.setAttribute('role', 'alert');
                errEl.innerHTML = '<div class="alert-icon"><i class="fas fa-exclamation-circle" aria-hidden="true"></i></div><div class="alert-content">Failed to create treatment plan. Please try again.</div>';
                btn.parentNode.insertBefore(errEl, btn.nextSibling);
                setTimeout(function () { if (errEl.parentNode) errEl.parentNode.removeChild(errEl); }, 6000);
            });
        });
    })();


    /* ============================================================
       10. PRINT HANDLER (results page)
       ============================================================ */
    (function PrintHandler() {
        var btn = document.getElementById('printReportBtn');
        if (btn) {
            btn.addEventListener('click', function () { window.print(); });
        }
    })();


    /* ============================================================
       11. SEVERITY DISPLAY (results page)
       Reads severity from sessionStorage, shows a severity badge.
       ============================================================ */
    (function SeverityDisplay() {
        var container = document.getElementById('severityDisplay');
        var content = document.getElementById('severityDisplayContent');
        if (!container || !content) return;

        var severity = sessionStorage.getItem('lastSeverity');
        if (!severity) return;

        var icons = { mild: '😌', moderate: '😟', severe: '😰' };
        var colors = {
            mild: 'var(--success)',
            moderate: 'var(--warning)',
            severe: 'var(--danger)'
        };
        var labels = { mild: 'Mild', moderate: 'Moderate', severe: 'Severe' };
        var descs = {
            mild: 'Barely noticeable symptoms',
            moderate: 'Symptoms affecting daily life',
            severe: 'Debilitating symptoms'
        };

        var icon = icons[severity] || '😐';
        var color = colors[severity] || 'var(--primary-600)';
        var label = labels[severity] || severity;
        var desc = descs[severity] || '';

        content.innerHTML = [
            '<div style="font-size:2.5rem; margin-bottom:8px;">' + icon + '</div>',
            '<div style="font-size:1.25rem; font-weight:700; color:' + color + ';">' + label + '</div>',
            '<div style="font-size:0.875rem; color:var(--text-muted); margin-top:4px;">' + desc + '</div>'
        ].join('');
        container.style.display = 'block';
    })();


}); // end DOMContentLoaded

// ============================================================================
// Form Validation (inline, no-reload)
// ============================================================================
(function FormValidation() {
    function showError(el, msg) {
        el.classList.add('is-invalid');
        var err = document.createElement('p');
        err.className = 'field-error';
        err.id = 'err-' + el.id;
        err.innerHTML = '<i class="fas fa-exclamation-circle" aria-hidden="true"></i> ' + msg;
        el.parentNode.insertBefore(err, el.nextSibling);
        el.focus();
    }
    function clearError(el) {
        if (!el) return;
        el.classList.remove('is-invalid', 'is-valid');
        var e = document.getElementById('err-' + el.id);
        if (e) e.remove();
    }

    // Symptom form (homepage)
    var analyzeForm = document.getElementById('analyzeForm');
    var sympInput = document.getElementById('symptoms');
    if (analyzeForm && sympInput) {
        analyzeForm.addEventListener('submit', function (e) {
            clearError(sympInput);
            if (!sympInput.value.trim() || sympInput.value.trim().length < 10) {
                e.preventDefault();
                showError(sympInput, 'Please describe your symptoms in at least 10 characters.');
            }
        });
    }

    // Login form
    var loginForm = document.querySelector('form[action*="login"]');
    if (loginForm) {
        loginForm.addEventListener('submit', function (e) {
            var u = loginForm.querySelector('#username');
            var p = loginForm.querySelector('#password');
            clearError(u); clearError(p);
            if (u && !u.value.trim()) { e.preventDefault(); showError(u, 'Username is required.'); return; }
            if (p && !p.value)        { e.preventDefault(); showError(p, 'Password is required.'); }
        });
    }

    // Signup form — password length + match
    var signupForm = document.querySelector('form[action*="signup"]');
    if (signupForm) {
        signupForm.addEventListener('submit', function (e) {
            var pw = signupForm.querySelector('#password');
            var cp = signupForm.querySelector('[name="confirm_password"]');
            if (pw && pw.value.length < 8) {
                e.preventDefault(); showError(pw, 'Password must be at least 8 characters.'); return;
            }
            if (pw && cp && pw.value !== cp.value) {
                e.preventDefault(); showError(cp, 'Passwords do not match.');
            }
        });
    }
})();

// ============================================================================
// Share Result
// ============================================================================
(function ShareResult() {
    var btn = document.getElementById('shareResultBtn');
    if (!btn) return;
    btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-result-id');
        var url = window.location.origin + '/results/' + id;
        if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function () {
                btn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                setTimeout(function () {
                    btn.innerHTML = '<i class="fas fa-share-alt"></i> Share Results';
                }, 2000);
            });
        } else {
            window.prompt('Copy this link:', url);
        }
    });
})();
