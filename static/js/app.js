document.addEventListener("DOMContentLoaded", () => {
    const API_BASE = window.RESEARCH_ALIGNMENT_API_URL || "";

    // --- Element references ---
    // Tabs
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabPanels = document.querySelectorAll(".tab-panel");

    // Upload mode
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const filePreview = document.getElementById("file-preview");
    const fileName = document.getElementById("file-name");
    const removeFileBtn = document.getElementById("remove-file");
    const submitBtn = document.getElementById("submit-btn");

    // Manual entry mode
    const expertiseInput = document.getElementById("expertise-input");
    const manualSubmitBtn = document.getElementById("manual-submit-btn");

    // Directory mode
    const expertSearch = document.getElementById("expert-search");
    const activeFiltersEl = document.getElementById("active-filters");
    const expertCount = document.getElementById("expert-count");
    const expertList = document.getElementById("expert-list");
    const directoryLoading = document.getElementById("directory-loading");

    // Shared views
    const processingView = document.getElementById("processing-view");
    const resultsView = document.getElementById("results-view");
    const errorView = document.getElementById("error-view");
    const statusText = document.getElementById("status-text");
    const errorMessage = document.getElementById("error-message");
    const retryBtn = document.getElementById("retry-btn");
    const copyBtn = document.getElementById("copy-btn");
    const newBtn = document.getElementById("new-btn");
    const methodologyToggle = document.getElementById("methodology-toggle");
    const methodologyPanel = document.getElementById("methodology-panel");

    let selectedFile = null;
    let lastResults = null;
    let facultyData = null;
    let activeFilters = [];
    let activeTab = "upload";

    // ===========================================
    // TAB MANAGEMENT
    // ===========================================

    function switchTab(tabId) {
        activeTab = tabId;
        tabBtns.forEach(btn => {
            const isActive = btn.dataset.tab === tabId;
            btn.classList.toggle("active", isActive);
            btn.setAttribute("aria-selected", isActive);
        });
        tabPanels.forEach(panel => {
            panel.classList.toggle("active", panel.id === `tab-${tabId}`);
        });
        // Hide shared views when switching tabs
        hideSharedViews();

        // Load faculty data when switching to directory for the first time
        if (tabId === "directory" && !facultyData) {
            loadFacultyData();
        }
    }

    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    function hideSharedViews() {
        processingView.hidden = true;
        resultsView.hidden = true;
        errorView.hidden = true;
    }

    function showSharedView(view) {
        // Hide tab panels when showing shared views
        tabPanels.forEach(p => p.classList.remove("active"));
        hideSharedViews();
        view.hidden = false;
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function returnToActiveTab() {
        hideSharedViews();
        tabPanels.forEach(panel => {
            panel.classList.toggle("active", panel.id === `tab-${activeTab}`);
        });
    }

    // ===========================================
    // MODE 1: FILE UPLOAD
    // ===========================================

    function setFile(file) {
        if (!file) return;
        const ext = file.name.split(".").pop().toLowerCase();
        if (!["pdf", "txt"].includes(ext)) {
            showError("Only PDF and TXT files are supported.");
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            showError("File is too large. Maximum size is 10 MB.");
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        filePreview.hidden = false;
        dropZone.style.display = "none";
        submitBtn.disabled = false;
    }

    function clearFile() {
        selectedFile = null;
        fileInput.value = "";
        filePreview.hidden = true;
        dropZone.style.display = "";
        submitBtn.disabled = true;
    }

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            setFile(e.dataTransfer.files[0]);
        }
    });

    dropZone.addEventListener("click", (e) => {
        if (e.target.closest(".file-btn")) return;
        fileInput.click();
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) setFile(fileInput.files[0]);
    });
    removeFileBtn.addEventListener("click", clearFile);

    // Processing status messages
    const statusMessages = [
        "Extracting document text",
        "Analyzing opportunity requirements",
        "Evaluating faculty expertise",
        "Ranking alignment"
    ];

    function cycleStatus() {
        let idx = 0;
        return setInterval(() => {
            idx = (idx + 1) % statusMessages.length;
            statusText.textContent = statusMessages[idx];
        }, 4000);
    }

    // Submit file upload
    submitBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        showSharedView(processingView);
        const interval = cycleStatus();

        const formData = new FormData();
        formData.append("file", selectedFile);

        try {
            const response = await fetch(API_BASE + "/api/match", {
                method: "POST",
                body: formData
            });

            clearInterval(interval);

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || `Server error (${response.status})`);
            }

            const data = await response.json();
            lastResults = data;
            renderResults(data);
            showSharedView(resultsView);
        } catch (err) {
            clearInterval(interval);
            showError(err.message);
        }
    });

    // ===========================================
    // MODE 2: MANUAL EXPERTISE ENTRY
    // ===========================================

    expertiseInput.addEventListener("input", () => {
        manualSubmitBtn.disabled = expertiseInput.value.trim().length < 20;
    });

    manualSubmitBtn.addEventListener("click", async () => {
        const text = expertiseInput.value.trim();
        if (text.length < 20) return;

        showSharedView(processingView);
        statusText.textContent = "Analyzing expertise requirements";
        const interval = cycleStatus();

        try {
            const response = await fetch(API_BASE + "/api/match-text", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text })
            });

            clearInterval(interval);

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || `Server error (${response.status})`);
            }

            const data = await response.json();
            lastResults = data;
            renderResults(data);
            showSharedView(resultsView);
        } catch (err) {
            clearInterval(interval);
            showError(err.message);
        }
    });

    // ===========================================
    // MODE 3: EXPERT DIRECTORY
    // ===========================================

    async function loadFacultyData() {
        directoryLoading.hidden = false;
        try {
            const response = await fetch(API_BASE + "/api/faculty");
            if (!response.ok) throw new Error("Failed to load faculty directory");
            facultyData = await response.json();
            directoryLoading.hidden = true;
            renderExpertList();
        } catch (err) {
            directoryLoading.hidden = true;
            expertList.innerHTML = '<div class="card"><p>Could not load faculty directory. Please try again.</p></div>';
        }
    }

    function getSearchableText(f) {
        const parts = [
            f.first_name, f.last_name,
            f.title || "",
            f.research_interests || "",
            f.research_interests_enriched || "",
            ...(f.expertise_keywords || []),
            ...(f.disease_areas || []),
            ...(f.methodologies || []),
            ...(f.populations || []),
            ...(f.committee_service || [])
        ];
        return parts.join(" ").toLowerCase();
    }

    function filterFaculty() {
        if (!facultyData) return [];
        const query = expertSearch.value.trim().toLowerCase();
        const terms = query ? query.split(/\s+/) : [];

        return facultyData.filter(f => {
            const text = getSearchableText(f);

            // Must match all search terms
            const matchesSearch = terms.length === 0 || terms.every(t => text.includes(t));

            // Must match all active filter chips
            const matchesFilters = activeFilters.length === 0 ||
                activeFilters.every(filter => text.includes(filter.toLowerCase()));

            return matchesSearch && matchesFilters;
        });
    }

    function renderExpertList() {
        const filtered = filterFaculty();
        expertCount.textContent = `${filtered.length} faculty${filtered.length !== facultyData.length ? ` of ${facultyData.length}` : ""}`;

        if (filtered.length === 0) {
            expertList.innerHTML = '<div class="card"><p style="color:var(--gray-500);font-size:var(--text-small);">No faculty match the current search criteria.</p></div>';
            return;
        }

        expertList.innerHTML = filtered.map((f, idx) => buildExpertCard(f, idx)).join("");

        // Attach click handlers for expand/collapse
        expertList.querySelectorAll(".expert-card").forEach(card => {
            card.addEventListener("click", (e) => {
                // Don't toggle if clicking a link or tag
                if (e.target.closest("a") || e.target.closest(".tag")) return;
                card.classList.toggle("expanded");
            });
        });

        // Attach click handlers for keyword tags (add as filter)
        expertList.querySelectorAll(".expert-keywords .tag").forEach(tag => {
            tag.addEventListener("click", (e) => {
                e.stopPropagation();
                const keyword = tag.textContent.trim();
                if (!activeFilters.includes(keyword)) {
                    activeFilters.push(keyword);
                    renderActiveFilters();
                    renderExpertList();
                }
            });
        });
    }

    function buildExpertCard(f) {
        const degrees = (f.degrees || []).join(", ");
        const nameStr = `${f.first_name} ${f.last_name}${degrees ? ", " + degrees : ""}`;
        const keywords = (f.expertise_keywords || []).slice(0, 8);
        const research = f.research_interests_enriched || f.research_interests || "";
        const diseaseAreas = f.disease_areas || [];
        const methods = f.methodologies || [];
        const pops = f.populations || [];
        const committees = f.committee_service || [];
        const grants = f.funded_grants || [];
        const pubs = f.recent_publications || [];

        let detailsHtml = "";

        // Research summary
        if (research) {
            detailsHtml += `
                <div class="expert-section">
                    <div class="expert-section-title">Research</div>
                    <p class="expert-research">${escapeHtml(research)}</p>
                </div>`;
        }

        // Meta grid: disease areas, methods, populations
        const metaParts = [];
        if (diseaseAreas.length > 0) {
            metaParts.push(`<div class="expert-meta-item"><strong>Disease Areas</strong><br>${escapeHtml(diseaseAreas.join(", "))}</div>`);
        }
        if (methods.length > 0) {
            metaParts.push(`<div class="expert-meta-item"><strong>Methods</strong><br>${escapeHtml(methods.join(", "))}</div>`);
        }
        if (pops.length > 0) {
            metaParts.push(`<div class="expert-meta-item"><strong>Populations</strong><br>${escapeHtml(pops.join(", "))}</div>`);
        }
        if (f.h_index) {
            metaParts.push(`<div class="expert-meta-item"><strong>h-index</strong><br>${f.h_index}</div>`);
        }
        if (metaParts.length > 0) {
            detailsHtml += `<div class="expert-section"><div class="expert-meta-grid">${metaParts.join("")}</div></div>`;
        }

        // Committee service
        if (committees.length > 0) {
            detailsHtml += `
                <div class="expert-section expert-committee">
                    <div class="expert-section-title">Committee Service</div>
                    ${committees.map(c => `<span class="committee-badge">${escapeHtml(c)}</span>`).join(" ")}
                </div>`;
        }

        // Funded grants (show up to 3)
        if (grants.length > 0) {
            const grantItems = grants.slice(0, 3).map(g =>
                `<li>${escapeHtml(g.title || "Untitled")} <span class="grant-agency">${escapeHtml(g.agency || "")}${g.start_date ? " (" + g.start_date + (g.end_date ? "–" + g.end_date : "") + ")" : ""}</span></li>`
            ).join("");
            detailsHtml += `
                <div class="expert-section">
                    <div class="expert-section-title">Funded Projects (${grants.length})</div>
                    <ul class="expert-grants-list">${grantItems}</ul>
                </div>`;
        }

        // Recent publications (show up to 3)
        if (pubs.length > 0) {
            const pubItems = pubs.slice(0, 3).map(p =>
                `<li>${escapeHtml(p.title || "Untitled")} <span class="pub-journal">${escapeHtml(p.journal || "")}${p.year ? " (" + p.year + ")" : ""}</span></li>`
            ).join("");
            detailsHtml += `
                <div class="expert-section">
                    <div class="expert-section-title">Recent Publications (${pubs.length})</div>
                    <ul class="expert-pubs-list">${pubItems}</ul>
                </div>`;
        }

        // Contact & links
        let contactHtml = "";
        if (f.email) {
            contactHtml += `<span class="expert-email"><a href="mailto:${escapeHtml(f.email)}">${escapeHtml(f.email)}</a></span>`;
        }
        if (f.profile_url) {
            contactHtml += `${f.email ? " &middot; " : ""}<span class="expert-profile-link"><a href="${escapeHtml(f.profile_url)}" target="_blank" rel="noopener">UCSD Profile</a></span>`;
        }
        if (contactHtml) {
            detailsHtml += `<div class="expert-section">${contactHtml}</div>`;
        }

        const hIndexHtml = f.h_index ? `<span class="expert-hindex">h-${f.h_index}</span>` : "";

        return `
        <div class="expert-card">
            <div class="expert-card-header">
                <div>
                    <div class="expert-name">${escapeHtml(nameStr)}</div>
                    <div class="expert-title">${escapeHtml(f.title || "")}</div>
                </div>
                ${hIndexHtml}
            </div>
            <div class="expert-keywords">
                ${keywords.map(k => `<span class="tag">${escapeHtml(k)}</span>`).join("")}
            </div>
            <div class="expert-details">
                ${detailsHtml}
            </div>
        </div>`;
    }

    // Search handler with debounce
    let searchTimeout = null;
    expertSearch.addEventListener("input", () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            renderExpertList();
        }, 200);
    });

    // Active filters
    function renderActiveFilters() {
        activeFiltersEl.innerHTML = activeFilters.map((f, i) =>
            `<span class="filter-chip" data-index="${i}">${escapeHtml(f)} <span class="chip-remove">&times;</span></span>`
        ).join("");

        activeFiltersEl.querySelectorAll(".filter-chip").forEach(chip => {
            chip.addEventListener("click", () => {
                const idx = parseInt(chip.dataset.index);
                activeFilters.splice(idx, 1);
                renderActiveFilters();
                renderExpertList();
            });
        });
    }

    // ===========================================
    // SHARED: ERROR HANDLING
    // ===========================================

    function showError(msg) {
        errorMessage.textContent = msg;
        showSharedView(errorView);
    }

    retryBtn.addEventListener("click", () => {
        returnToActiveTab();
    });

    newBtn.addEventListener("click", () => {
        clearFile();
        lastResults = null;
        methodologyPanel.classList.remove("visible");
        returnToActiveTab();
    });

    // ===========================================
    // SHARED: RESULTS RENDERING
    // ===========================================

    methodologyToggle.addEventListener("click", (e) => {
        e.preventDefault();
        methodologyPanel.classList.toggle("visible");
        methodologyToggle.textContent = methodologyPanel.classList.contains("visible")
            ? "Hide ranking methodology"
            : "How rankings are calculated";
    });

    function renderResults(data) {
        const summary = data.grant_summary || {};

        // Opportunity title and agency
        const titleEl = document.getElementById("result-title");
        const agencyEl = document.getElementById("result-agency");
        titleEl.innerHTML = summary.grant_title
            ? `<strong>Title:</strong> ${escapeHtml(summary.grant_title)}`
            : "";
        agencyEl.innerHTML = summary.funding_agency
            ? `<strong>Agency:</strong> ${escapeHtml(summary.funding_agency)}`
            : "";

        // Brief summary
        const briefEl = document.getElementById("result-brief");
        briefEl.textContent = summary.grant_summary || "";
        briefEl.style.display = summary.grant_summary ? "" : "none";

        // Research themes
        const themesEl = document.getElementById("research-themes");
        const themes = summary.overall_research_themes || [];
        themesEl.innerHTML = themes.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("");

        // Requirements breakdown
        const reqBody = document.getElementById("requirements-body");
        reqBody.innerHTML = "";

        const invReqs = summary.investigator_requirements || [];
        if (invReqs.length > 0) {
            invReqs.forEach(req => {
                reqBody.appendChild(buildReqSection(
                    req.role || "Investigator",
                    {
                        expertise_areas: req.expertise_areas,
                        qualifications: req.qualifications,
                        constraints: req.constraints
                    }
                ));
            });
        } else {
            const piReq = summary.pi_requirements;
            if (piReq) {
                reqBody.appendChild(buildReqSection("Lead Investigator", piReq));
            }
            const coReq = summary.co_pi_requirements;
            if (coReq) {
                reqBody.appendChild(buildReqSection("Co-Investigator", coReq));
            }
            const keyPersonnel = summary.key_personnel || [];
            keyPersonnel.forEach((kp, i) => {
                reqBody.appendChild(buildReqSection(
                    kp.role || `Key Personnel ${i + 1}`,
                    { expertise_areas: kp.expertise_areas, qualifications: kp.qualifications, constraints: [] }
                ));
            });
        }

        // Match cards
        const matchesList = document.getElementById("matches-list");
        const matches = data.matches || [];
        if (matches.length === 0) {
            matchesList.innerHTML = '<div class="card"><p>No strong faculty alignments were found for this opportunity.</p></div>';
        } else {
            matchesList.innerHTML = matches.map(buildMatchCard).join("");
        }

        // Excluded note
        const excludedNote = document.getElementById("excluded-note");
        const excluded = data.faculty_without_interests_count || 0;
        const considered = data.total_faculty_considered || 0;
        excludedNote.textContent = `${considered} faculty evaluated \u00B7 ${excluded} excluded (no listed research interests)`;

        // Reset methodology panel
        methodologyPanel.classList.remove("visible");
        methodologyToggle.textContent = "How rankings are calculated";
    }

    function buildReqSection(title, req) {
        const div = document.createElement("div");
        div.className = "req-section";

        let html = `<h4>${escapeHtml(title)}</h4>`;
        const items = [
            ...(req.expertise_areas || []).map(e => `Expertise: ${e}`),
            ...(req.qualifications || []).map(q => `Qualification: ${q}`),
            ...(req.constraints || []).map(c => `Constraint: ${c}`)
        ];
        if (items.length > 0) {
            html += '<ul class="req-list">' + items.map(i => `<li>${escapeHtml(i)}</li>`).join("") + "</ul>";
        } else {
            html += '<p style="font-size:0.8125rem;color:#999;">No specific requirements listed</p>';
        }

        div.innerHTML = html;
        return div;
    }

    function buildMatchCard(match) {
        const degrees = (match.degrees || []).join(", ");
        const nameStr = `${match.first_name} ${match.last_name}${degrees ? ", " + degrees : ""}`;
        const score = match.match_score || 0;
        const scoreClass = score >= 80 ? "score-high" : score >= 60 ? "score-med" : "score-low";

        const expertise = match.expertise_alignment || 0;
        const methods = match.methodological_fit || 0;
        const track = match.track_record || 0;

        const emailHtml = match.email
            ? `<a href="mailto:${escapeHtml(match.email)}">${escapeHtml(match.email)}</a>`
            : '<span class="no-email">No email listed</span>';

        return `
        <div class="match-card">
            <div class="match-rank">${match.rank}</div>
            <div class="match-header">
                <div>
                    <div class="match-name">${escapeHtml(nameStr)}</div>
                    <div class="match-title">${escapeHtml(match.title || "")}</div>
                </div>
                <div class="score-overall">${score}</div>
            </div>
            <div class="score-bar-bg">
                <div class="score-bar-fill ${scoreClass}" style="width:${score}%"></div>
            </div>
            <div class="score-breakdown">
                <div class="score-dimension">
                    <span class="score-dim-label">Expertise</span>
                    <span class="score-dim-value">${expertise}</span>
                </div>
                <div class="score-dimension">
                    <span class="score-dim-label">Methods</span>
                    <span class="score-dim-value">${methods}</span>
                </div>
                <div class="score-dimension">
                    <span class="score-dim-label">Track Record</span>
                    <span class="score-dim-value">${track}</span>
                </div>
            </div>
            <p class="match-reasoning">${escapeHtml(match.match_reasoning || "")}</p>
            <p class="match-interests"><strong>Research:</strong> ${escapeHtml(match.research_interests || "")}</p>
            <div class="match-email">${emailHtml}</div>
        </div>`;
    }

    // ===========================================
    // COPY RESULTS
    // ===========================================

    copyBtn.addEventListener("click", () => {
        if (!lastResults) return;

        const summary = lastResults.grant_summary || {};
        let text = "Research Alignment Results — UC San Diego\n";
        text += "==========================================\n\n";
        if (summary.grant_title) text += `Opportunity: ${summary.grant_title}\n`;
        if (summary.funding_agency) text += `Agency: ${summary.funding_agency}\n`;
        if (summary.grant_summary) text += `\n${summary.grant_summary}\n`;
        text += "\n";

        const matches = lastResults.matches || [];
        matches.forEach(m => {
            const degrees = (m.degrees || []).join(", ");
            text += `${m.rank}. ${m.first_name} ${m.last_name}, ${degrees}\n`;
            text += `   Score: ${m.match_score} (Expertise: ${m.expertise_alignment || "\u2014"}, Methods: ${m.methodological_fit || "\u2014"}, Track Record: ${m.track_record || "\u2014"})\n`;
            text += `   ${m.match_reasoning}\n`;
            if (m.email) text += `   Email: ${m.email}\n`;
            text += "\n";
        });

        navigator.clipboard.writeText(text).then(() => {
            const original = copyBtn.textContent;
            copyBtn.textContent = "Copied";
            setTimeout(() => { copyBtn.textContent = original; }, 2000);
        });
    });

    // ===========================================
    // UTILITY
    // ===========================================

    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }
});
