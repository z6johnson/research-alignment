document.addEventListener("DOMContentLoaded", () => {
    const API_BASE = window.GRANT_MATCH_API_URL || "";

    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const filePreview = document.getElementById("file-preview");
    const fileName = document.getElementById("file-name");
    const removeFileBtn = document.getElementById("remove-file");
    const submitBtn = document.getElementById("submit-btn");
    const uploadView = document.getElementById("upload-view");
    const processingView = document.getElementById("processing-view");
    const resultsView = document.getElementById("results-view");
    const errorView = document.getElementById("error-view");
    const statusText = document.getElementById("status-text");
    const errorMessage = document.getElementById("error-message");
    const retryBtn = document.getElementById("retry-btn");
    const copyBtn = document.getElementById("copy-btn");
    const newBtn = document.getElementById("new-btn");

    let selectedFile = null;
    let lastResults = null;

    // View management
    function showView(view) {
        [uploadView, processingView, resultsView, errorView].forEach(v => v.hidden = true);
        view.hidden = false;
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    // File selection
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

    // Drag and drop
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

    dropZone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) setFile(fileInput.files[0]);
    });
    removeFileBtn.addEventListener("click", clearFile);

    // Processing status messages
    const statusMessages = [
        "Extracting document text...",
        "Analyzing grant requirements...",
        "Matching faculty expertise...",
        "Ranking candidates..."
    ];

    function cycleStatus() {
        let idx = 0;
        return setInterval(() => {
            idx = (idx + 1) % statusMessages.length;
            statusText.textContent = statusMessages[idx];
        }, 4000);
    }

    // Submit
    submitBtn.addEventListener("click", async () => {
        if (!selectedFile) return;

        showView(processingView);
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
            showView(resultsView);
        } catch (err) {
            clearInterval(interval);
            showError(err.message);
        }
    });

    // Error display
    function showError(msg) {
        errorMessage.textContent = msg;
        showView(errorView);
    }

    retryBtn.addEventListener("click", () => {
        clearFile();
        showView(uploadView);
    });

    newBtn.addEventListener("click", () => {
        clearFile();
        lastResults = null;
        showView(uploadView);
    });

    // Render results
    function renderResults(data) {
        const summary = data.grant_summary || {};

        // Grant title and agency
        const titleEl = document.getElementById("grant-title");
        const agencyEl = document.getElementById("grant-agency");
        titleEl.innerHTML = summary.grant_title
            ? `<strong>Title:</strong> ${escapeHtml(summary.grant_title)}`
            : "";
        agencyEl.innerHTML = summary.funding_agency
            ? `<strong>Agency:</strong> ${escapeHtml(summary.funding_agency)}`
            : "";

        // Research themes
        const themesEl = document.getElementById("research-themes");
        const themes = summary.overall_research_themes || [];
        themesEl.innerHTML = themes.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("");

        // Requirements breakdown
        const reqBody = document.getElementById("requirements-body");
        reqBody.innerHTML = "";

        const piReq = summary.pi_requirements;
        if (piReq) {
            reqBody.appendChild(buildReqSection("Principal Investigator (PI)", piReq));
        }
        const coReq = summary.co_pi_requirements;
        if (coReq) {
            reqBody.appendChild(buildReqSection("Co-Principal Investigator (Co-PI)", coReq));
        }
        const keyPersonnel = summary.key_personnel || [];
        keyPersonnel.forEach((kp, i) => {
            reqBody.appendChild(buildReqSection(
                kp.role || `Key Personnel ${i + 1}`,
                { expertise_areas: kp.expertise_areas, qualifications: kp.qualifications, constraints: [] }
            ));
        });

        // Match cards
        const matchesList = document.getElementById("matches-list");
        const matches = data.matches || [];
        if (matches.length === 0) {
            matchesList.innerHTML = '<div class="card"><p>No strong faculty matches were found for this grant.</p></div>';
        } else {
            matchesList.innerHTML = matches.map(buildMatchCard).join("");
        }

        // Excluded note
        const excludedNote = document.getElementById("excluded-note");
        const excluded = data.faculty_without_interests_count || 0;
        const considered = data.total_faculty_considered || 0;
        excludedNote.textContent = `${considered} faculty evaluated \u00B7 ${excluded} excluded (no listed research interests)`;
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
            html += '<p style="font-size:0.85rem;color:#999;">No specific requirements listed</p>';
        }

        div.innerHTML = html;
        return div;
    }

    function buildMatchCard(match) {
        const degrees = (match.degrees || []).join(", ");
        const nameStr = `${match.first_name} ${match.last_name}${degrees ? ", " + degrees : ""}`;
        const score = match.match_score || 0;
        const scoreClass = score >= 80 ? "score-high" : score >= 60 ? "score-med" : "score-low";
        const roleClass = getRoleClass(match.recommended_role);
        const roleLabel = match.recommended_role || "Key Personnel";

        const emailHtml = match.email
            ? `<a href="mailto:${escapeHtml(match.email)}">${escapeHtml(match.email)}</a>`
            : '<span class="no-email">No email listed</span>';

        return `
        <div class="match-card">
            <div class="match-header">
                <div>
                    <div class="match-name">${escapeHtml(nameStr)}</div>
                    <div class="match-title">${escapeHtml(match.title || "")}</div>
                </div>
                <span class="role-badge ${roleClass}">${escapeHtml(roleLabel)}</span>
            </div>
            <div class="score-row">
                <span class="score-label">${score}%</span>
                <div class="score-bar-bg">
                    <div class="score-bar-fill ${scoreClass}" style="width:${score}%"></div>
                </div>
            </div>
            <p class="match-reasoning">${escapeHtml(match.match_reasoning || "")}</p>
            <p class="match-interests"><strong>Research:</strong> ${escapeHtml(match.research_interests || "")}</p>
            <div class="match-email">${emailHtml}</div>
        </div>`;
    }

    function getRoleClass(role) {
        if (!role) return "role-key";
        const r = role.toLowerCase();
        if (r === "pi") return "role-pi";
        if (r === "co-pi") return "role-co-pi";
        if (r === "consultant") return "role-consultant";
        return "role-key";
    }

    // Copy results
    copyBtn.addEventListener("click", () => {
        if (!lastResults) return;

        const summary = lastResults.grant_summary || {};
        let text = "UCSD Grant Match Results\n";
        text += "========================\n\n";
        if (summary.grant_title) text += `Grant: ${summary.grant_title}\n`;
        if (summary.funding_agency) text += `Agency: ${summary.funding_agency}\n`;
        text += "\n";

        const matches = lastResults.matches || [];
        matches.forEach(m => {
            const degrees = (m.degrees || []).join(", ");
            text += `${m.rank}. ${m.first_name} ${m.last_name}, ${degrees}\n`;
            text += `   Role: ${m.recommended_role} | Score: ${m.match_score}%\n`;
            text += `   ${m.match_reasoning}\n`;
            if (m.email) text += `   Email: ${m.email}\n`;
            text += "\n";
        });

        navigator.clipboard.writeText(text).then(() => {
            const original = copyBtn.textContent;
            copyBtn.textContent = "Copied!";
            setTimeout(() => { copyBtn.textContent = original; }, 2000);
        });
    });

    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }
});
