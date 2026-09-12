document.addEventListener('alpine:init', () => Alpine.data('pilot', () => ({
  stats: {}, channels: [], total: 0, page: 1, query: '', filter: '', message: '', error: '',
  editing: null, draft: {}, saving: false, editError: '', sequence: 0, timer: null,
  async init() { await this.refresh(); this.timer = setInterval(() => this.refresh(), 5000); },
  destroy() { clearInterval(this.timer); },
  async request(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-Pilot-Request': '1' } });
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the entered values.');
    return body;
  },
  async refresh() {
    try { this.stats = await this.request('/api/status'); await this.load(); }
    catch (e) { this.error = e.message; }
  },
  async load() {
    const seq = ++this.sequence;
    try {
      const params = new URLSearchParams({ q: this.query, page: this.page });
      if (this.filter) params.set('status', this.filter);
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
  }
})));
