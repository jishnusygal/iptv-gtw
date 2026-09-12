document.addEventListener('alpine:init', () => Alpine.data('pilot', () => ({
  stats: {}, channels: [], total: 0, page: 1, query: '', filter: '', country: '', language: [], group: '', languageSearch: '',
  filterOptions: { countries: [], languages: [], groups: [] }, message: '', error: '',
  editing: null, draft: {}, saving: false, editError: '', sequence: 0, timer: null,
  jellyfin: { url: '', urlDetected: false, apiKey: '', apiKeySet: false, baseUrl: '', baseUrlDetected: false, autoSync: false, lastPush: null, error: null, saving: false, pushing: false },
  async init() {
    this.loadFilterOptions();
    this.loadJellyfin();
    await this.refresh();
    this.timer = setInterval(() => this.refresh(), 5000);
  },
  destroy() { clearInterval(this.timer); },
  async request(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-Pilot-Request': '1' } });
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the entered values.');
    return body;
  },
  async loadFilterOptions() {
    try { this.filterOptions = await this.request('/api/filters'); }
    catch (e) { this.error = e.message; }
  },
  async refresh() {
    try {
      const wasRunning = this.stats.job?.running;
      const [stats] = await Promise.all([this.request('/api/status'), this.load()]);
      this.stats = stats;
      if (wasRunning && !stats.job?.running) this.loadFilterOptions();
    } catch (e) { this.error = e.message; }
  },
  hasFilters() { return !!(this.query || this.filter || this.country || this.language.length || this.group); },
  toggleLanguage(l) {
    const i = this.language.indexOf(l);
    if (i === -1) this.language.push(l); else this.language.splice(i, 1);
    this.page = 1; this.load();
  },
  filteredLanguages() {
    const q = this.languageSearch.trim().toLowerCase();
    return q ? this.filterOptions.languages.filter(l => l.toLowerCase().includes(q)) : this.filterOptions.languages;
  },
  async load() {
    const seq = ++this.sequence;
    try {
      const params = new URLSearchParams({ q: this.query, page: this.page });
      for (const [key, value] of Object.entries({ status: this.filter, country: this.country, group_title: this.group })) {
        if (value) params.set(key, value);
      }
      for (const l of this.language) params.append('language', l);
      const data = await this.request('/api/channels?' + params);
      if (seq !== this.sequence) return;
      this.channels = data.items; this.total = data.total; this.error = '';
    } catch (e) { this.error = e.message; }
  },
  health(c) { return c.streams.some(s => s.status === 'ONLINE') ? 'ONLINE' : c.streams.some(s => s.status === 'UNTESTED') ? 'UNTESTED' : c.streams.length ? 'OFFLINE' : 'NO STREAMS'; },
  async job(name) {
    try { await this.request('/api/' + name, { method: 'POST', body: '{}' }); this.message = 'Background job accepted.'; await this.refresh(); }
    catch (e) { this.error = e.message; }
  },
  async toggle(c) {
    try { await this.request('/api/channels/' + c.id, { method: 'PATCH', body: JSON.stringify({ is_enabled: !c.is_enabled }) }); await this.load(); }
    catch (e) { this.error = e.message; }
  },
  openEdit(c) {
    this.editing = c; this.editError = '';
    this.draft = { channel_number: c.channel_number, name: c.name, tvg_name: c.tvg_name || '', group_title: c.group_title, epg_id: c.epg_id || '' };
    this.$refs.editor.showModal();
  },
  async save() {
    this.saving = true;
    try {
      await this.request('/api/channels/' + this.editing.id, { method: 'PATCH', body: JSON.stringify({ ...this.draft, epg_id: this.draft.epg_id || null, tvg_name: this.draft.tvg_name || null }) });
      this.$refs.editor.close(); this.message = 'Channel updated.'; await this.load();
    } catch (e) { this.editError = e.message; }
    finally { this.saving = false; }
  },
  async copy(id) {
    const input = document.getElementById(id);
    try { await navigator.clipboard.writeText(input.value); this.message = 'Endpoint copied.'; }
    catch { input.select(); this.message = 'Select and copy the endpoint from the field.'; }
  },
  async loadJellyfin() {
    try {
      const data = await this.request('/api/jellyfin');
      this.jellyfin = { ...this.jellyfin, url: data.url || '', urlDetected: data.url_detected, apiKey: '', apiKeySet: data.api_key_set,
        baseUrl: data.base_url || '', baseUrlDetected: data.base_url_detected, autoSync: data.auto_sync, lastPush: data.last_push, error: data.last_error };
    } catch (e) { this.jellyfin.error = e.message; }
  },
  async saveJellyfin() {
    this.jellyfin.saving = true; this.jellyfin.error = null;
    try {
      await this.request('/api/jellyfin', { method: 'POST', body: JSON.stringify({
        url: this.jellyfin.url, api_key: this.jellyfin.apiKey, base_url: this.jellyfin.baseUrl, auto_sync: this.jellyfin.autoSync }) });
      this.message = 'Jellyfin connection saved.'; await this.loadJellyfin();
    } catch (e) { this.jellyfin.error = e.message; }
    finally { this.jellyfin.saving = false; }
  },
  async pushJellyfin() {
    this.jellyfin.pushing = true; this.jellyfin.error = null;
    try {
      const result = await this.request('/api/jellyfin/push', { method: 'POST', body: '{}' });
      this.message = result.confirmed ? 'Jellyfin fetched the playlist successfully.' : 'Registered with Jellyfin — its guide refresh is still finishing; check back shortly.';
      await this.loadJellyfin();
    } catch (e) { this.jellyfin.error = e.message; }
    finally { this.jellyfin.pushing = false; }
  },
  async logout() {
    try { await fetch('/logout', { method: 'POST' }); } finally { window.location.href = '/login'; }
  }
})));
