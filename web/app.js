// SABADARMON MSKT PACS APP.JS
let activeTabId = 'studies-archive';

// -------------------------------------------------------------
// 1. LIGHTWEIGHT MODAL / DIALOG (YENGIL MARKAZIY OYNA)
// -------------------------------------------------------------
function showDialog({ title = "Bildirishnoma", message, onConfirm = null, confirmText = "Ha", cancelText = "Bekor qilish" }) {
    const backdrop = document.getElementById('custom-modal-backdrop');
    const titleEl = document.getElementById('modal-title');
    const msgEl = document.getElementById('modal-message');
    const footerEl = document.getElementById('modal-footer');
    
    if (!backdrop || !titleEl || !msgEl || !footerEl) return;

    titleEl.innerText = title;
    msgEl.innerText = message;
    
    if (onConfirm) {
        footerEl.innerHTML = `
            <button class="btn btn-secondary btn-sm" onclick="closeCustomModal()">${cancelText}</button>
            <button class="btn btn-primary btn-sm" id="btn-modal-confirm">${confirmText}</button>
        `;
        document.getElementById('btn-modal-confirm').onclick = () => {
            closeCustomModal();
            onConfirm();
        };
    } else {
        footerEl.innerHTML = `<button class="btn btn-primary btn-sm" onclick="closeCustomModal()">Tushunarli</button>`;
    }
    backdrop.classList.add('active');
}

function closeCustomModal() {
    const backdrop = document.getElementById('custom-modal-backdrop');
    if (backdrop) backdrop.classList.remove('active');
}

function handleBackdropClick(e) {
    if (e.target.id === 'custom-modal-backdrop') {
        closeCustomModal();
    }
}

// -------------------------------------------------------------
// 2. TAB BOSHQARUVI
// -------------------------------------------------------------
function switchTab(tabId) {
    activeTabId = tabId;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));

    const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick')?.includes(tabId));
    if (activeBtn) activeBtn.classList.add('active');

    const targetTab = document.getElementById(`tab-${tabId}`);
    if (targetTab) targetTab.classList.add('active');

    if (tabId === 'studies-archive') loadStudies();
    if (tabId === 'system-logs') loadLogs();
}

function closeAlert() {
    const banner = document.getElementById('ct-direct-alert');
    if (banner) banner.style.display = 'none';
}

// -------------------------------------------------------------
// 3. ARXIV VA BEMORLAR BOSHQARUVI (727+ STUDIES)
// -------------------------------------------------------------
let allStudies = [];
let filteredStudies = [];
let currentStudyFilter = 'ALL';
let currentSearchQuery = '';
let currentStudyPage = 1;
let studyPageSize = 50;
let selectedStudyIds = new Set();
let activeProgressPollTimer = null;

function formatUzbekDate(dateStr) {
    if (!dateStr) return "";
    const months = {
        1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel",
        5: "may", 6: "iyun", 7: "iyul", 8: "avgust",
        9: "sentabr", 10: "oktabr", 11: "noyabr", 12: "dekabr"
    };
    const s = String(dateStr).trim();
    const digits = s.replace(/\D/g, "");
    if (digits.length >= 8) {
        const y = parseInt(digits.slice(0, 4));
        const m = parseInt(digits.slice(4, 6));
        const d = parseInt(digits.slice(6, 8));
        if (m >= 1 && m <= 12 && d >= 1 && d <= 31) {
            const dd = d < 10 ? '0' + d : d;
            return `${dd}-${months[m]} ${y}`;
        }
    }
    return s;
}

function updateSelectedCount() {
    const countSpan = document.getElementById('selected-count');
    const batchBtn = document.getElementById('btn-batch-telegram');
    if (countSpan) countSpan.innerText = selectedStudyIds.size;
    if (batchBtn) batchBtn.disabled = (selectedStudyIds.size === 0);
}

function toggleStudySelect(id, checkbox) {
    if (checkbox.checked) {
        selectedStudyIds.add(id);
    } else {
        selectedStudyIds.delete(id);
    }
    updateSelectedCount();
    
    const allCheckboxes = document.querySelectorAll('.study-checkbox');
    const master = document.getElementById('select-all-studies');
    if (master && allCheckboxes.length > 0) {
        master.checked = Array.from(allCheckboxes).every(cb => cb.checked);
    }
}

function toggleSelectAllStudies(masterCheckbox) {
    const allCheckboxes = document.querySelectorAll('.study-checkbox');
    allCheckboxes.forEach(cb => {
        cb.checked = masterCheckbox.checked;
        const id = parseInt(cb.value);
        if (masterCheckbox.checked) {
            selectedStudyIds.add(id);
        } else {
            selectedStudyIds.delete(id);
        }
    });
    updateSelectedCount();
}

let currentDatePreset = 'ALL';
let currentExamFilter = 'ALL';
let currentSortBy = 'DATE_DESC';

function populateExamFilterOptions() {
    const examSelect = document.getElementById('filter-exam-select');
    if (!examSelect) return;
    const currentVal = examSelect.value;
    const exams = new Set();
    allStudies.forEach(s => {
        const desc = (s.study_description || '').trim();
        if (desc && desc !== '-' && desc !== 'None') {
            exams.add(desc);
        }
    });
    const sortedExams = Array.from(exams).sort();
    examSelect.innerHTML = `<option value="ALL">Barcha sohalar</option>` + sortedExams.map(e => `<option value="${e}">${e}</option>`).join('');
    if (sortedExams.includes(currentVal)) {
        examSelect.value = currentVal;
    }
}

function handleDatePresetChange(val) {
    currentDatePreset = val;
    const customInput = document.getElementById('filter-date-custom');
    if (customInput) {
        customInput.style.display = (val === 'CUSTOM') ? 'inline-block' : 'none';
        if (val !== 'CUSTOM') customInput.value = '';
    }
    currentStudyPage = 1;
    applyStudyFilters();
}

function handleSortChange(val) {
    currentSortBy = val;
    applyStudyFilters();
}

function resetAllFilters() {
    currentSearchQuery = '';
    currentStudyFilter = 'ALL';
    currentDatePreset = 'ALL';
    currentExamFilter = 'ALL';
    currentSortBy = 'DATE_DESC';

    const searchInput = document.getElementById('study-search-input');
    if (searchInput) searchInput.value = '';
    const datePreset = document.getElementById('filter-date-preset');
    if (datePreset) datePreset.value = 'ALL';
    const dateCustom = document.getElementById('filter-date-custom');
    if (dateCustom) { dateCustom.value = ''; dateCustom.style.display = 'none'; }
    const examSelect = document.getElementById('filter-exam-select');
    if (examSelect) examSelect.value = 'ALL';
    const sortSelect = document.getElementById('filter-sort-by');
    if (sortSelect) sortSelect.value = 'DATE_DESC';

    document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    const allBtn = document.querySelector('.filter-pill[onclick*="ALL"]');
    if (allBtn) allBtn.classList.add('active');

    currentStudyPage = 1;
    applyStudyFilters();
}

function updateFilterCounts() {
    const total = allStudies.length;
    const inProgressCount = allStudies.filter(s => {
        const st = s.active_stage || '';
        return (st === 'DOWNLOADING_CT' || st === 'ARCHIVING' || st === 'UPLOADING_TG' || s.telegram_status === 'RETRIEVING' || s.telegram_status === 'SENDING');
    }).length;
    const storedCount = allStudies.filter(s => s.has_local_copy).length;
    const ctCount = allStudies.filter(s => s.telegram_status === 'ON_CT_DEVICE').length;
    const sentCount = allStudies.filter(s => s.telegram_status === 'SENT').length;
    const failedCount = allStudies.filter(s => s.telegram_status === 'FAILED').length;

    const elAll = document.getElementById('filter-all-count');
    const elProg = document.getElementById('filter-progress-count');
    const elStored = document.getElementById('filter-stored-count');
    const elCt = document.getElementById('filter-ct-count');
    const elSent = document.getElementById('filter-sent-count');
    const elFailed = document.getElementById('filter-failed-count');

    if (elAll) elAll.innerText = total;
    if (elProg) elProg.innerText = inProgressCount;
    if (elStored) elStored.innerText = storedCount;
    if (elCt) elCt.innerText = ctCount;
    if (elSent) elSent.innerText = sentCount;
    if (elFailed) elFailed.innerText = failedCount;
}

function handleStudySearch(query) {
    currentSearchQuery = (query || '').toLowerCase().trim();
    currentStudyPage = 1;
    applyStudyFilters();
}

function setStudyFilter(filterKey, buttonElem) {
    currentStudyFilter = filterKey;
    currentStudyPage = 1;
    document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    if (buttonElem) buttonElem.classList.add('active');
    applyStudyFilters();
}

function applyStudyFilters() {
    const examSelect = document.getElementById('filter-exam-select');
    const selectedExam = examSelect ? examSelect.value : 'ALL';
    const customDateInput = document.getElementById('filter-date-custom');
    const customDateVal = customDateInput ? customDateInput.value.replace(/-/g, '') : '';

    const now = new Date();
    const todayStr = now.toISOString().slice(0, 10).replace(/-/g, '');
    const yest = new Date(now.getTime() - 86400000);
    const yesterdayStr = yest.toISOString().slice(0, 10).replace(/-/g, '');
    const sevenDaysAgo = new Date(now.getTime() - 7 * 86400000);
    const sevenDaysAgoStr = sevenDaysAgo.toISOString().slice(0, 10).replace(/-/g, '');
    const thisMonthPrefix = now.toISOString().slice(0, 7).replace(/-/g, '');

    filteredStudies = allStudies.filter(s => {
        // Status pill filter
        if (currentStudyFilter === 'IN_PROGRESS') {
            const st = s.active_stage || '';
            const isProg = (st === 'DOWNLOADING_CT' || st === 'ARCHIVING' || st === 'UPLOADING_TG' || s.telegram_status === 'RETRIEVING' || s.telegram_status === 'SENDING');
            if (!isProg) return false;
        } else if (currentStudyFilter === 'LOCAL_STORED') {
            if (!s.has_local_copy) return false;
        } else if (currentStudyFilter === 'ON_CT_DEVICE') {
            if (s.telegram_status !== 'ON_CT_DEVICE') return false;
        } else if (currentStudyFilter === 'SENT') {
            if (s.telegram_status !== 'SENT') return false;
        } else if (currentStudyFilter === 'FAILED') {
            if (s.telegram_status !== 'FAILED') return false;
        }

        // Exam description filter
        if (selectedExam !== 'ALL') {
            if ((s.study_description || '').trim() !== selectedExam) return false;
        }

        // Date filter
        const sDate = String(s.study_date || '').replace(/\D/g, '');
        if (currentDatePreset === 'TODAY') {
            if (sDate !== todayStr) return false;
        } else if (currentDatePreset === 'YESTERDAY') {
            if (sDate !== yesterdayStr) return false;
        } else if (currentDatePreset === 'LAST_7_DAYS') {
            if (sDate < sevenDaysAgoStr || sDate > todayStr) return false;
        } else if (currentDatePreset === 'THIS_MONTH') {
            if (!sDate.startsWith(thisMonthPrefix)) return false;
        } else if (currentDatePreset === 'CUSTOM' && customDateVal) {
            if (sDate !== customDateVal) return false;
        }

        // Search query filter (F.I.Sh, ID, description, date)
        if (currentSearchQuery) {
            const name = (s.patient_name || '').toLowerCase();
            const pid = (s.patient_id || '').toLowerCase();
            const desc = (s.study_description || '').toLowerCase();
            const date = (s.study_date || '').toLowerCase();
            if (!name.includes(currentSearchQuery) && !pid.includes(currentSearchQuery) && !desc.includes(currentSearchQuery) && !date.includes(currentSearchQuery)) {
                return false;
            }
        }
        return true;
    });

    // Sorting
    filteredStudies.sort((a, b) => {
        if (currentSortBy === 'DATE_DESC') {
            return String(b.study_date || '').localeCompare(String(a.study_date || '')) || String(b.study_time || '').localeCompare(String(a.study_time || ''));
        } else if (currentSortBy === 'DATE_ASC') {
            return String(a.study_date || '').localeCompare(String(b.study_date || '')) || String(a.study_time || '').localeCompare(String(b.study_time || ''));
        } else if (currentSortBy === 'NAME_ASC') {
            return String(a.patient_name || '').localeCompare(String(b.patient_name || ''));
        } else if (currentSortBy === 'NAME_DESC') {
            return String(b.patient_name || '').localeCompare(String(a.patient_name || ''));
        } else if (currentSortBy === 'INSTANCES_DESC') {
            return (b.instances_count || 0) - (a.instances_count || 0);
        } else if (currentSortBy === 'INSTANCES_ASC') {
            return (a.instances_count || 0) - (b.instances_count || 0);
        }
        return 0;
    });

    renderStudiesTable();
}

function changePageSize(newSize) {
    studyPageSize = parseInt(newSize) || 50;
    currentStudyPage = 1;
    
    // Ikkala selektorni sinxronlash
    const topSel = document.getElementById('select-page-size-top');
    if (topSel) topSel.value = String(studyPageSize);
    const btmSel = document.getElementById('select-page-size-bottom');
    if (btmSel) btmSel.value = String(studyPageSize);

    renderStudiesTable();
}

function goToStudyPage(pageNum) {
    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    if (pageNum >= 1 && pageNum <= totalPages) {
        currentStudyPage = pageNum;
        renderStudiesTable();

        // Agar pastdan bosilgan bo'lsa, jadval boshiga silliq olib chiqish
        const tableCard = document.querySelector('.table-responsive');
        if (tableCard) {
            tableCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
}

function changeStudyPage(delta) {
    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    const newPage = currentStudyPage + delta;
    if (newPage >= 1 && newPage <= totalPages) {
        goToStudyPage(newPage);
    }
}

function renderGooglePagination() {
    const container = document.getElementById('bottom-google-pagination');
    if (!container) return;

    if (filteredStudies.length === 0) {
        container.innerHTML = '';
        return;
    }

    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    const startIdx = (currentStudyPage - 1) * studyPageSize;
    const endIdx = Math.min(startIdx + studyPageSize, filteredStudies.length);

    // Google ranglar palitrasi: Moviy, Qizil, Sariq, Yashil
    const colors = ['#4285F4', '#EA4335', '#FBBC05', '#34A853'];

    // Ko'rsatiladigan sahifalar oralig'i (maksimal 10 ta sahifa darchasi)
    const maxVisible = 10;
    let startPage = Math.max(1, currentStudyPage - Math.floor(maxVisible / 2));
    let endPage = startPage + maxVisible - 1;
    if (endPage > totalPages) {
        endPage = totalPages;
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    // Har bir sahifa uchun Google harflari ('o' lar)
    let lettersHtml = '';
    for (let p = startPage; p <= endPage; p++) {
        const isActive = (p === currentStudyPage);
        const color = isActive ? '#EA4335' : colors[(p - 1) % colors.length];
        lettersHtml += `
            <div class="google-letter-col ${isActive ? 'active' : ''}" onclick="goToStudyPage(${p})" title="${p}-sahifaga o'tish">
                <span class="g-char" style="color: ${color}; ${isActive ? 'font-size: 2.3rem;' : ''}">o</span>
                <span class="g-num">${p}</span>
            </div>
        `;
    }

    const hasPrev = currentStudyPage > 1;
    const hasNext = currentStudyPage < totalPages;

    const prevHtml = hasPrev
        ? `<div class="google-nav-btn" onclick="goToStudyPage(${currentStudyPage - 1})" title="Oldingi sahifa">
               <span style="font-size: 1.15rem; line-height: 1;">‹</span> Oldingisi
           </div>`
        : `<div class="google-nav-btn disabled">‹ Oldingisi</div>`;

    const nextHtml = hasNext
        ? `<div class="google-nav-btn" onclick="goToStudyPage(${currentStudyPage + 1})" title="Keyingi sahifa">
               Keyingisi <span style="font-size: 1.15rem; line-height: 1;">›</span>
           </div>`
        : `<div class="google-nav-btn disabled">Keyingisi ›</div>`;

    container.innerHTML = `
        <div class="google-brand-title">
            <span class="brand-leaf">🌿</span>
            <span class="brand-word">Sabadarmon</span>
            <span class="brand-sub">MSKT PACS & Worklist</span>
        </div>
        <div class="google-letters-row">
            ${prevHtml}
            <div style="display: flex; align-items: flex-end; gap: 2px;">
                <span class="g-char" style="color: #4285F4; margin-right: 1px;">S</span>
                ${lettersHtml}
                <span class="g-char" style="color: #4285F4; margin-left: 1px;">n</span>
            </div>
            ${nextHtml}
        </div>
        <div class="google-bottom-meta">
            <div>
                Ko'rsatilmoqda: <strong>${startIdx + 1}–${endIdx}</strong> / Jami: <strong>${filteredStudies.length}</strong> ta bemor (${currentStudyPage} / ${totalPages} sahifa)
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <span style="font-weight: 600;">📄 Sahifada:</span>
                <select id="select-page-size-bottom" class="form-input" style="width: auto; padding: 4px 8px; margin: 0; font-weight: 600;" onchange="changePageSize(this.value)">
                    <option value="50" ${studyPageSize === 50 ? 'selected' : ''}>50 ta bemor</option>
                    <option value="100" ${studyPageSize === 100 ? 'selected' : ''}>100 ta bemor</option>
                    <option value="200" ${studyPageSize === 200 ? 'selected' : ''}>200 ta bemor</option>
                    <option value="500" ${studyPageSize === 500 ? 'selected' : ''}>500 ta bemor</option>
                    <option value="1000" ${studyPageSize === 1000 ? 'selected' : ''}>1000 ta bemor</option>
                    <option value="999999" ${studyPageSize >= 999999 ? 'selected' : ''}>Barchasi (Hammasi)</option>
                </select>
            </div>
        </div>
    `;
}

function renderStudiesTable() {
    const tbody = document.getElementById('studies-tbody');
    const master = document.getElementById('select-all-studies');
    if (master) master.checked = false;

    if (filteredStudies.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: #94a3b8; padding: 24px;">Hech qanday tekshiruv topilmadi.</td></tr>`;
        
        const topInfo = document.getElementById('top-pagination-info');
        const topTotal = document.getElementById('top-pagination-total');
        const topPageDisp = document.getElementById('top-page-num-display');
        const btnTopPrev = document.getElementById('btn-top-prev');
        const btnTopNext = document.getElementById('btn-top-next');
        if (topInfo) topInfo.innerText = "0 - 0";
        if (topTotal) topTotal.innerText = "0";
        if (topPageDisp) topPageDisp.innerText = "1 / 1";
        if (btnTopPrev) btnTopPrev.disabled = true;
        if (btnTopNext) btnTopNext.disabled = true;

        renderGooglePagination();
        return;
    }

    const totalPages = Math.ceil(filteredStudies.length / studyPageSize) || 1;
    if (currentStudyPage > totalPages) currentStudyPage = totalPages;

    const startIdx = (currentStudyPage - 1) * studyPageSize;
    const endIdx = Math.min(startIdx + studyPageSize, filteredStudies.length);
    const pageItems = filteredStudies.slice(startIdx, endIdx);

    // Yuqori sahifalash satrini yangilash
    const topInfo = document.getElementById('top-pagination-info');
    const topTotal = document.getElementById('top-pagination-total');
    const topPageDisp = document.getElementById('top-page-num-display');
    const btnTopPrev = document.getElementById('btn-top-prev');
    const btnTopNext = document.getElementById('btn-top-next');
    const selTopSize = document.getElementById('select-page-size-top');

    if (topInfo) topInfo.innerText = `${startIdx + 1}–${endIdx}`;
    if (topTotal) topTotal.innerText = filteredStudies.length;
    if (topPageDisp) topPageDisp.innerText = `${currentStudyPage} / ${totalPages}`;
    if (btnTopPrev) btnTopPrev.disabled = (currentStudyPage <= 1);
    if (btnTopNext) btnTopNext.disabled = (currentStudyPage >= totalPages);
    if (selTopSize) selTopSize.value = String(studyPageSize);

    // Pastki Google sahifalashni chizish
    renderGooglePagination();

    tbody.innerHTML = pageItems.map(s => {
        const sizeMb = s.archive_size_bytes ? (s.archive_size_bytes / (1024 * 1024)).toFixed(1) + ' MB' : '-';
        const uzDate = formatUzbekDate(s.study_date);
        const isChecked = selectedStudyIds.has(s.id);

        // 1. Mahalliy xotirada saqlanish holati (30 kunlik muddat)
        let storageBadge = '';
        if (s.has_local_copy) {
            storageBadge = `
                <span class="badge-storage-local" title="Fayllar diskda mavjud">💾 Serverda (${sizeMb})</span>
                <div style="color: #64748b; font-size: 0.73rem; margin-top: 3px;">🕒 ${s.days_remaining} kun qoldi</div>
            `;
        } else {
            storageBadge = `<span class="badge-storage-remote" title="Fayllar faqat KT apparatida saqlanmoqda">☁️ Faqat KT da</span>`;
        }

        // 2. Telegram holati va dinamik progress
        let statusBadge = '';
        let actionBtn = '';
        const stage = s.active_stage || '';
        const percent = s.active_percent || 0;
        const progressText = s.active_text || '';

        if (stage === 'DOWNLOADING_CT') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-retrieving" style="font-size: 0.72rem;">📥 ${progressText || 'KT dan yuklanmoqda: ' + percent + '%'}</span>
                    <div class="progress-track"><div class="progress-fill ct-download" style="width: ${percent}%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-download" disabled>⏳ Yuklanmoqda...</button>`;
        } else if (stage === 'ARCHIVING') {
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-retrieving" style="font-size: 0.72rem;">🗜️ ZIP qilinmoqda...</span>
                    <div class="progress-track"><div class="progress-fill ct-download" style="width: 95%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-download" disabled>🗜️ Siqilmoqda...</button>`;
        } else if (stage === 'UPLOADING_TG') {
            const speedInfo = s.active_speed ? ` • ⚡ ${s.active_speed}` : '';
            const tgText = progressText || `Telegramga: ${percent}%${speedInfo}`;
            statusBadge = `
                <div class="progress-container">
                    <span class="badge-status status-sending" style="font-size: 0.72rem; font-weight: 600;" title="${tgText}">📤 ${tgText}</span>
                    <div class="progress-track"><div class="progress-fill tg-upload" style="width: ${percent}%;"></div></div>
                </div>
            `;
            actionBtn = `<button class="btn btn-sm btn-action-resend" disabled>📤 Yuklanmoqda...</button>`;
        } else if (s.telegram_status === 'SENT') {
            statusBadge = '<span class="badge-status status-sent">✅ Yuborildi</span>';
            actionBtn = `<button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})">📤 Telegram</button>`;
        } else if (s.telegram_status === 'ON_CT_DEVICE') {
            statusBadge = '<span class="badge-status status-on-ct" title="Fayllar KT apparatida">💾 KT Qurilmada</span>';
            actionBtn = `
                <button class="btn btn-sm btn-action-download" onclick="downloadToServer(${s.id})" title="Faqat serverga yuklab olish">📥 Serverga</button>
                <button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})" title="Telegramga yuborish">📤 Telegram</button>
            `;
        } else if (s.telegram_status === 'FAILED') {
            statusBadge = '<span class="badge-status status-failed">❌ Xatolik</span>';
            actionBtn = `<button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})">🔄 Qayta urinish</button>`;
        } else {
            statusBadge = '<span class="badge-status status-pending">⏳ Kutilmoqda</span>';
            actionBtn = `<button class="btn btn-sm btn-action-resend" onclick="resendTelegram(${s.id})">📤 Telegram</button>`;
        }

        return `
        <tr id="study-row-${s.id}" style="${isChecked ? 'background: #eff6ff;' : ''}">
            <td style="text-align: center;">
                <input type="checkbox" class="study-checkbox" value="${s.id}" ${isChecked ? 'checked' : ''} onchange="toggleStudySelect(${s.id}, this)">
            </td>
            <td><strong>${uzDate}</strong> <small style="color:#64748b;">${s.study_time || ''}</small></td>
            <td><code>${s.patient_id || '-'}</code></td>
            <td><strong>${s.patient_name || '-'}</strong></td>
            <td>${s.study_description || '-'}</td>
            <td><strong>${s.instances_count}</strong> kadr</td>
            <td>${storageBadge}</td>
            <td id="status-cell-${s.id}">${statusBadge}</td>
            <td style="display: flex; gap: 6px; align-items: center;" id="action-cell-${s.id}">
                ${s.has_local_copy ? `<button class="btn btn-sm btn-action-view" onclick="openInRadiAnt(${s.id})" title="RadiAnt dasturida ochish">🔍 RadiAnt</button>` : ''}
                ${actionBtn}
            </td>
        </tr>
        `;
    }).join('');

    updateSelectedCount();
}

// Barcha tekshiruvlarni serverdan yuklash
async function loadStudies() {
    try {
        const res = await fetch('/api/studies');
        allStudies = await res.json();
        const archCount = document.getElementById('archive-count');
        if (archCount) archCount.innerText = allStudies.length;

        updateFilterCounts();
        populateExamFilterOptions();
        applyStudyFilters();
        checkActiveProgresses();
    } catch (err) {
        console.error("Studies yuklashda xatolik:", err);
    }
}

// Faol progresslarni avtomatik tekshiruvchi funksiya (Live Polling)
async function checkActiveProgresses() {
    try {
        const res = await fetch('/api/studies/progress');
        const progressMap = await res.json();
        const activeIds = Object.keys(progressMap);

        let hasActiveTasks = false;
        activeIds.forEach(idStr => {
            const id = parseInt(idStr);
            const p = progressMap[idStr];
            if (p && (p.stage === 'DOWNLOADING_CT' || p.stage === 'ARCHIVING' || p.stage === 'UPLOADING_TG')) {
                hasActiveTasks = true;
                // Mahalliy xotirada mavjud study obyektini yangilash
                const study = allStudies.find(s => s.id === id);
                if (study) {
                    study.active_stage = p.stage;
                    study.active_percent = p.percent;
                    study.active_text = p.text;
                    study.active_speed = p.speed || '';
                }
            } else if (p && p.stage === 'DONE') {
                const study = allStudies.find(s => s.id === id);
                if (study) {
                    study.telegram_status = 'SENT';
                    study.active_stage = 'DONE';
                    study.has_local_copy = true;
                }
            } else if (p && p.stage === 'ERROR') {
                const study = allStudies.find(s => s.id === id);
                if (study) {
                    study.telegram_status = 'FAILED';
                    study.active_stage = 'ERROR';
                    study.active_text = p.text || 'Xatolik';
                }
            }
        });

        if (hasActiveTasks) {
            renderStudiesTable();
            if (!activeProgressPollTimer) {
                activeProgressPollTimer = setInterval(checkActiveProgresses, 800);
            }
        } else {
            if (activeProgressPollTimer) {
                clearInterval(activeProgressPollTimer);
                activeProgressPollTimer = null;
                // Yakuniy yangilash
                setTimeout(loadStudies, 1000);
            }
        }
    } catch (e) {
        console.error("Progress tekshirishda xatolik:", e);
    }
}

// KT apparatidagi barcha bemorlarni sinxronlash
async function syncAllCT() {
    const btn = document.getElementById('btn-sync-ct');
    const oldText = btn ? btn.innerText : '';
    if (btn) {
        btn.innerText = "⏳ So'ralmoqda...";
        btn.disabled = true;
    }
    try {
        const res = await fetch('/api/sync_ct', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showDialog({
                title: "KT Sinxronizatsiyasi",
                message: `✅ KT apparatidagi barcha bemorlar muvaffaqiyatli sinxronlandi! Jami: ${data.count} ta tekshiruv.`
            });
            await loadStudies();
        } else {
            showDialog({ title: "Xatolik", message: data.detail || "Sinxronlab bo'lmadi" });
        }
    } catch (err) {
        showDialog({ title: "Tarmoq xatosi", message: err.toString() });
    } finally {
        if (btn) {
            btn.innerText = oldText;
            btn.disabled = false;
        }
    }
}

// Tanlanganlarni bir nechta qilib Telegramga yuborish
async function resendSelectedStudies() {
    if (selectedStudyIds.size === 0) return;

    showDialog({
        title: "Telegramga yuborish",
        message: `${selectedStudyIds.size} ta tekshiruvni Telegram kanaliga yuborishni tasdiqlaysizmi?\n(KT apparatidagi fayllar avtomatik yuklab olinadi va Telegramga yetkaziladi)`,
        confirmText: "Yuborish",
        onConfirm: async () => {
            try {
                const res = await fetch('/api/studies/batch_resend', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ study_ids: Array.from(selectedStudyIds) })
                });
                const data = await res.json();
                if (res.ok) {
                    showDialog({
                        title: "Boshlandi",
                        message: `✅ ${data.count} ta tekshiruv navbatga qo'yildi va yuklash boshlandi!`
                    });
                    selectedStudyIds.clear();
                    const master = document.getElementById('select-all-studies');
                    if (master) master.checked = false;
                    updateSelectedCount();
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuborib bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// RadiAnt'da ochish
async function openInRadiAnt(id) {
    const study = allStudies.find(s => s.id === id);
    if (study && !study.has_local_copy && study.telegram_status === 'ON_CT_DEVICE') {
        showDialog({
            title: "RadiAnt xabari",
            message: `Ushbu tekshiruv (${study.patient_name || ''}) hozircha faqat KT apparatida saqlanmoqda. Uni avval kompyuterga yuklab olishni xohlaysizmi?`,
            confirmText: "Yuklab olish",
            onConfirm: () => downloadToServer(id)
        });
        return;
    }

    try {
        const res = await fetch(`/api/studies/${id}/open_radiant`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showDialog({
                title: "RadiAnt xabari",
                message: data.detail || "Fayllar topilmadi. Avval '📥 Serverga' tugmasi orqali yuklab oling."
            });
        }
    } catch (err) {
        showDialog({ title: "RadiAnt xatosi", message: err.toString() });
    }
}

// Bitta bemorni faqat serverga yuklab olish (Telegramga yubormasdan)
async function downloadToServer(id) {
    const study = allStudies.find(s => s.id === id);
    if (!study) return;

    showDialog({
        title: "Serverga yuklab olish",
        message: `Ushbu tekshiruv (${study.patient_name || ''}) KT apparatidan ushbu kompyuterga yuklab olinadi va arxivlanadi.\n(Telegramga yuborilmaydi)`,
        confirmText: "Yuklab olish",
        onConfirm: async () => {
            try {
                study.active_stage = 'DOWNLOADING_CT';
                study.active_percent = 5;
                study.active_text = 'KT dan olinmoqda...';
                renderStudiesTable();

                const res = await fetch(`/api/studies/${id}/download_to_server`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuklab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// Bitta bemorni Telegramga yuborish / KT dan tortish
async function resendTelegram(id) {
    const study = allStudies.find(s => s.id === id);
    const isCt = study && study.telegram_status === 'ON_CT_DEVICE';
    const confirmPrompt = isCt
        ? `Ushbu tekshiruv (${study?.patient_name || ''}) KT apparatidan tortib olinadi va Telegram kanaliga yuboriladi. Davom etasizmi?`
        : `Ushbu tekshiruvni (${study?.patient_name || ''}) Telegram kanaliga yuborishni xohlaysizmi?`;

    showDialog({
        title: "Tasdiqlash",
        message: confirmPrompt,
        confirmText: "Yuborish",
        onConfirm: async () => {
            try {
                // UI da darhol holatni o'zgartirish
                if (study) {
                    study.active_stage = isCt ? 'DOWNLOADING_CT' : 'UPLOADING_TG';
                    study.active_percent = 1;
                    study.active_text = isCt ? 'KT apparatidan olinmoqda...' : 'Telegram serveriga ulanmoqda... 0% • ⚡ 0.0 MB/s';
                    study.active_speed = '0.0 MB/s';
                    renderStudiesTable();
                }

                const res = await fetch(`/api/studies/${id}/resend`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    checkActiveProgresses();
                } else {
                    showDialog({ title: "Xatolik", message: data.detail || "Yuklab bo'lmadi" });
                }
            } catch (err) {
                showDialog({ title: "Tarmoq xatosi", message: err.toString() });
            }
        }
    });
}

// -------------------------------------------------------------
// 4. TIZIM VA DICOM LOGLARI
// -------------------------------------------------------------
async function loadLogs() {
    try {
        const res = await fetch('/api/logs?limit=80');
        const logs = await res.json();
        const container = document.getElementById('logs-container');
        if (!container || logs.length === 0) return;

        container.innerHTML = logs.map(l => {
            const time = l.created_at ? l.created_at.replace('T', ' ').substring(11, 19) : '';
            return `
            <div class="log-entry ${l.level}">
                <span style="color: #64748b;">[${time}]</span>
                <strong>[${l.level}]</strong> ${l.message}
            </div>
            `;
        }).join('');
    } catch (err) {
        console.error("Loglar yuklashda xatolik:", err);
    }
}

// -------------------------------------------------------------
// 5. STATUS TEKSHIRUVI VA INISTSIALIZATSIYA
// -------------------------------------------------------------
async function checkSystemStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const ctText = document.getElementById('ct-status-text');
        const ctBadge = document.getElementById('ct-status-badge');
        if (ctBadge && ctText) {
            const dot = ctBadge.querySelector('.dot');
            if (data.ct_online) {
                ctText.innerText = "Ulangan (Online)";
                if (dot) dot.className = "dot green";
            } else {
                ctText.innerText = "Kutilmoqda / Tekshirilmoqda";
                if (dot) dot.className = "dot yellow";
            }
        }

        const diskText = document.getElementById('disk-free-text');
        if (diskText) {
            diskText.innerText = `${data.disk_free_gb} GB (${data.disk_used_percent}% band)`;
        }
    } catch (err) {
        console.error("Status tekshirishda xatolik:", err);
    }
}

// Boshlang'ich yuklash
document.addEventListener('DOMContentLoaded', () => {
    checkSystemStatus();
    loadStudies();
    loadLogs();

    setInterval(checkSystemStatus, 15000);
    setInterval(loadLogs, 4000);
});

// -------------------------------------------------------------
// 6. SOZLAMALAR MODAL BOSHQARUVI
// -------------------------------------------------------------
async function openSettingsModal() {
    const backdrop = document.getElementById('settings-modal-backdrop');
    if (!backdrop) return;
    try {
        const res = await fetch('/api/settings');
        if (res.ok) {
            const cfg = await res.json();
            document.getElementById('setting-ct-host').value = cfg.ct_host || '';
            document.getElementById('setting-ct-port').value = cfg.ct_port || 4006;
            document.getElementById('setting-ct-aet').value = cfg.ct_aet || 'CT01';
            document.getElementById('setting-pacs-port').value = cfg.pacs_port || 11112;
            document.getElementById('setting-pacs-aet').value = cfg.pacs_aet || 'RADIANT';
            document.getElementById('setting-web-port').value = cfg.web_port || 8000;
            document.getElementById('setting-retention-days').value = cfg.retention_days || 30;
            document.getElementById('setting-tg-token').value = cfg.telegram_bot_token || '';
            document.getElementById('setting-tg-channel').value = cfg.telegram_channel_id || '';
            if (document.getElementById('setting-auto-archive')) {
                document.getElementById('setting-auto-archive').checked = cfg.auto_archive_enabled !== false;
            }
            if (document.getElementById('setting-poll-interval')) {
                document.getElementById('setting-poll-interval').value = cfg.new_study_poll_interval || 60;
            }
            if (document.getElementById('setting-stability-checks')) {
                document.getElementById('setting-stability-checks').value = cfg.recon_stability_checks || 3;
            }
            if (document.getElementById('setting-deep-scan')) {
                document.getElementById('setting-deep-scan').value = cfg.deep_scan_interval || 10800;
            }
            if (document.getElementById('setting-batch-conc')) {
                document.getElementById('setting-batch-conc').value = cfg.batch_concurrency || 2;
            }
        }
    } catch (e) {
        console.error("Sozlamalarni olishda xatolik:", e);
    }
    backdrop.classList.add('active');
}

function closeSettingsModal() {
    const backdrop = document.getElementById('settings-modal-backdrop');
    if (backdrop) backdrop.classList.remove('active');
}

function handleSettingsBackdropClick(e) {
    if (e.target.id === 'settings-modal-backdrop') {
        closeSettingsModal();
    }
}

async function saveSettingsFromModal() {
    const payload = {
        ct_host: document.getElementById('setting-ct-host').value.trim(),
        ct_port: parseInt(document.getElementById('setting-ct-port').value) || 4006,
        ct_aet: document.getElementById('setting-ct-aet').value.trim() || 'CT01',
        pacs_port: parseInt(document.getElementById('setting-pacs-port').value) || 11112,
        pacs_aet: document.getElementById('setting-pacs-aet').value.trim() || 'RADIANT',
        web_port: parseInt(document.getElementById('setting-web-port').value) || 8000,
        retention_days: parseInt(document.getElementById('setting-retention-days').value) || 30,
        telegram_bot_token: document.getElementById('setting-tg-token').value.trim(),
        telegram_channel_id: document.getElementById('setting-tg-channel').value.trim(),
        auto_archive_enabled: document.getElementById('setting-auto-archive') ? document.getElementById('setting-auto-archive').checked : true,
        new_study_poll_interval: parseInt(document.getElementById('setting-poll-interval')?.value) || 60,
        recon_stability_checks: parseInt(document.getElementById('setting-stability-checks')?.value) || 3,
        deep_scan_interval: parseInt(document.getElementById('setting-deep-scan')?.value) || 10800,
        batch_concurrency: parseInt(document.getElementById('setting-batch-conc')?.value) || 2
    };

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            closeSettingsModal();
            showDialog({
                title: "Saqlandi",
                message: "✅ Sozlamalar muvaffaqiyatli saqlandi va qo'llanildi!"
            });
            checkSystemStatus();
        } else {
            const err = await res.json();
            showDialog({ title: "Xatolik", message: err.detail || "Saqlab bo'lmadi" });
        }
    } catch (e) {
        showDialog({ title: "Xatolik", message: e.toString() });
    }
}
