"""Rich terminal administration of logical intent and read-only live observations."""
from datetime import datetime, timezone
import time
import uuid

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static, TabbedContent, TabPane

from .health import HealthState, host_resources
from .registry import BASELINE, RegistryError


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%H:%M:%S UTC') if value else 'never'


def size(value):
    return f'{value / 1024**3:.1f} GiB' if value is not None else 'unavailable'


class Form(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, registry, store=None, observability=False):
        super().__init__()
        self.registry, self.store, self.observability = registry, store, observability
        self.desired = (registry.read()['observability']['desired_state'] if observability
                        else store['desired_state'] if store else 'enabled')

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Static('OBSERVABILITY INTENT' if self.observability else 'CONFIGURE LOGICAL STORE' if self.store else 'REGISTER A STORE', classes='dialog-title')
            yield Static('Save logical configuration. Physical targets and deployment execution are deferred.', classes='dialog-note')
            with VerticalScroll(classes='form-fields'):
                if not self.observability and self.store is None:
                    yield Label('Stable store ID')
                    yield Input(placeholder='STORE-DE-01', id='store-id', max_length=48)
                    yield Label('Store display name')
                    yield Input(placeholder='Germany', id='store-name', max_length=64)
                    yield Label('Intended ISO country (not residency attestation)')
                    yield Input(placeholder='DE', id='country', max_length=2)
                if self.observability or self.store:
                    yield Label('Desired state · deployment adapter pending')
                    yield Select([('Enabled', 'enabled'), ('Suspended', 'suspended')],
                                 value=self.desired if self.desired != 'unmanaged' else 'enabled',
                                 allow_blank=False, id='desired-state')
                if not self.observability:
                    yield Label('Desired logical nodes (1–9) · retained IDs are reused')
                    yield Input(value=str(self.store['node_count'] if self.store else 1), type='integer', id='node-count', max_length=1)
            yield Static('', id='form-error', classes='error')
            with Horizontal(classes='dialog-buttons'):
                yield Button('Cancel', id='cancel-form')
                yield Button('Review configuration', variant='primary', id='review-form')

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, '#cancel-form')
    def cancel(self):
        self.action_cancel()

    @on(Button.Pressed, '#review-form')
    def review(self):
        try:
            if self.observability:
                action, payload = 'observability', {'desired_state': self.query_one('#desired-state', Select).value}
            elif self.store:
                action, payload = 'configure_store', {'id': self.store['id'],
                    'desired_state': self.query_one('#desired-state', Select).value,
                    'node_count': int(self.query_one('#node-count', Input).value)}
            else:
                action, payload = 'register_store', {'id': self.query_one('#store-id', Input).value.strip(),
                    'name': self.query_one('#store-name', Input).value.strip(),
                    'country': self.query_one('#country', Input).value.strip().upper(),
                    'node_count': int(self.query_one('#node-count', Input).value)}
            self.dismiss(self.registry.plan(action, payload))
        except (ValueError, RegistryError) as error:
            message = str(error) if isinstance(error, RegistryError) else 'Enter a logical node count between 1 and 9.'
            self.query_one('#form-error', Static).update(Text(message))


class Review(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, registry, plan):
        super().__init__()
        self.registry, self.plan = registry, plan
        self.request_id = str(uuid.uuid4())

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Static('REVIEW CONFIGURATION', classes='dialog-title')
            with VerticalScroll(classes='form-fields'):
                yield Static(Text(self.plan.summary), classes='review-summary')
                yield Static(Text('\n\n'.join('• ' + c for c in self.plan.changes)), id='review-changes')
                yield Static('SAVE INTENT ONLY\nDeployment adapter pending. No containers, VMs, SQL data, policies or running telemetry are changed.', classes='boundary')
                yield Static(f'Reviewed revision: {self.plan.base_revision}\nRequest UUID: {self.request_id}', classes='dialog-note')
            yield Static('', id='review-error', classes='error')
            with Horizontal(classes='dialog-buttons'):
                yield Button('Back / cancel', id='cancel-review')
                yield Button('Save configuration', variant='primary', id='save-review')

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, '#cancel-review')
    def cancel(self):
        self.action_cancel()

    @on(Button.Pressed, '#save-review')
    def save(self):
        try:
            self.dismiss(self.registry.save(self.plan, self.request_id))
        except RegistryError as error:
            self.query_one('#review-error', Static).update(Text(str(error)))
            # Keep the plan and UUID for a genuinely uncertain write retry.
            if 'since review' in str(error):
                self.query_one('#save-review', Button).disabled = True


class Information(ModalScreen):
    BINDINGS = [('escape', 'close', 'Close')]

    def __init__(self, title, body):
        super().__init__()
        self.heading, self.body = title, body

    def compose(self) -> ComposeResult:
        with Vertical(classes='dialog'):
            yield Static(self.heading, classes='dialog-title')
            with VerticalScroll(classes='form-fields'):
                yield Static(Text(self.body))
            yield Button('Close', id='close-information')

    def action_close(self):
        self.dismiss()

    @on(Button.Pressed, '#close-information')
    def close(self):
        self.action_close()


class AdminApp(App):
    TITLE = 'Sovereign · Lab Admin'
    SUB_TITLE = 'Logical topology + live health'
    BINDINGS = [Binding('a', 'add_store', 'Add store'), Binding('e', 'configure_store', 'Configure'),
                Binding('o', 'observability', 'Observability'), Binding('r', 'refresh_health', 'Refresh'),
                Binding('p', 'pause_health', 'Pause polling'), Binding('/', 'search', 'Find'),
                Binding('question_mark', 'help', 'Help'), Binding('q', 'quit', 'Quit')]
    CSS = '''
    Screen { background: #0b1424; color: #edf3fc; }
    Header { background: #162841; color: #edf3fc; }
    Footer { background: #162841; }
    #mode { height: 2; background: #183a43; color: #b8efe4; padding: 0 2; }
    #metrics { height: 3; padding: 0 2; background: #101f34; color: #c9d9ee; }
    #resize-note { display: none; background: #653625; color: #fff0d7; height: 2; }
    #registry-warning { display: none; height: auto; background: #693138; color: #fff3f4; }
    TabbedContent { height: 1fr; }
    ContentSwitcher { height: 1fr; }
    TabPane { padding: 0 1; }
    Tabs { background: #101f34; }
    Tab.-active { color: #7de5ce; text-style: bold; }
    #store-layout { height: 1fr; }
    #store-list { width: 52%; padding-right: 1; }
    #store-detail { width: 48%; border: round #31516a; padding: 0 1; }
    #store-search { height: 3; margin: 0; }
    DataTable { background: #101f34; color: #edf3fc; height: 1fr; }
    DataTable > .datatable--header { background: #203750; color: #c8ede4; text-style: bold; }
    DataTable > .datatable--cursor { background: #235b61; color: #ffffff; }
    #detail-title { height: auto; color: #8ce7d5; text-style: bold; margin-bottom: 1; }
    #detail-body { height: auto; }
    #node-table { height: auto; max-height: 12; margin-top: 1; }
    #store-actions, #store-actions-health { height: 3; }
    Button { min-width: 12; margin-right: 1; }
    Button.-primary { background: #136e66; color: #ffffff; }
    .section { height: auto; padding: 1; border: round #31516a; margin-bottom: 1; }
    .section-title { height: auto; color: #8ce7d5; text-style: bold; }
    .note { height: auto; color: #bfcee1; }
    #health-note { height: auto; padding: 0 1; }
    #activity-note { height: auto; padding: 0 1; }
    ModalScreen { align: center middle; background: #000000 65%; }
    .dialog { width: 76; max-width: 95%; height: 85%; border: thick #4a9b9b; background: #122239; padding: 1 2; }
    .dialog-title { height: 2; color: #9ae8d8; text-style: bold; }
    .dialog-note { height: auto; color: #c7d5e8; margin-bottom: 1; }
    .form-fields { height: 1fr; }
    .form-fields > Label { margin-top: 1; height: auto; }
    Input, Select { height: 3; }
    .error { height: auto; color: #ffc3bd; }
    .dialog-buttons { height: 3; margin-top: 1; }
    .review-summary { height: auto; text-style: bold; margin-bottom: 1; }
    #review-changes { height: auto; }
    .boundary { height: auto; border: round #ca9b50; color: #ffe1a4; padding: 1; margin: 1 0; }
    AdminApp.narrow #store-layout { layout: vertical; }
    AdminApp.narrow #store-list { width: 100%; height: 1fr; padding: 0; }
    AdminApp.narrow #store-detail { width: 100%; height: 7; }
    AdminApp.narrow #metrics { height: 2; }
    AdminApp.narrow #mode { height: 2; }
    AdminApp.too-small #resize-note { display: block; }
    '''

    def __init__(self, registry, observer, *, interval=10, auto_health=True):
        super().__init__()
        self.registry, self.observer = registry, observer
        self.state = registry.read()
        self.health = HealthState()
        self.selected = self.state['stores'][0]['id']
        self.auto_health, self.polling, self.interval = auto_health, False, interval
        self.registry_valid = True
        self.last_current = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static('LOGICAL CONTROL PLANE  •  Live observations when available\nSaved intent awaits a deployment adapter; backend targets remain unassigned.', id='mode')
        yield Static('', id='resize-note')
        yield Static('', id='registry-warning')
        yield Static('', id='metrics')
        with TabbedContent(initial='stores-tab', id='tabs'):
            with TabPane('Stores & nodes', id='stores-tab'):
                with Horizontal(id='store-layout'):
                    with Vertical(id='store-list'):
                        yield Input(placeholder='Search store, country or ID  [/]', id='store-search')
                        yield DataTable(id='store-table', cursor_type='row', zebra_stripes=True)
                        with Horizontal(id='store-actions'):
                            yield Button('Add store', id='add-store', variant='primary')
                            yield Button('Configure', id='configure-store')
                    with VerticalScroll(id='store-detail'):
                        yield Static('', id='detail-title')
                        yield Static('', id='detail-body')
                        yield DataTable(id='node-table', cursor_type='row')
            with TabPane('Environment', id='environment-tab'):
                with VerticalScroll():
                    with Vertical(classes='section'):
                        yield Static('OBSERVABILITY', classes='section-title')
                        yield Static('', id='observability-summary')
                        yield Button('Change intent', id='change-observability', variant='primary')
                    with Vertical(classes='section'):
                        yield Static('SHARED HOST RESOURCES', classes='section-title')
                        yield Static('', id='resources')
                    yield Static('Business SQL audit: REQUIRED\nHealth polling is independent of observability. Infrastructure execution and target binding are deferred.', classes='note')
            with TabPane('Health', id='health-tab'):
                yield Static('', id='health-note')
                yield DataTable(id='health-table', cursor_type='row', zebra_stripes=True)
                with Horizontal(id='store-actions-health'):
                    yield Button('Refresh health', id='refresh-health', variant='primary')
                    yield Button('Pause polling', id='pause-health')
            with TabPane('Activity', id='activity-tab'):
                yield Static('Configuration receipts · latest 100 displayed; all retained in the state file. Enter opens a receipt.', id='activity-note')
                yield DataTable(id='activity-table', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self):
        self.query_one('#store-table', DataTable).add_columns('Store / country', 'Intent', 'Observed')
        self.query_one('#node-table', DataTable).add_columns('Logical node', 'Intent', 'Physical target')
        self.query_one('#health-table', DataTable).add_columns('Store', 'SQL', 'OPA', 'Observation')
        self.query_one('#activity-table', DataTable).add_columns('Rev', 'Action', 'Summary', 'Request UUID')
        self.render_state()
        self.query_one('#store-table', DataTable).focus()
        self.set_interval(self.interval, self.auto_refresh)
        self.set_interval(1, self.clock_tick)
        self.set_classes_for_size(self.size.width, self.size.height)
        if self.auto_health:
            self.action_refresh_health()

    def set_classes_for_size(self, width, height):
        self.set_class(width < 110, 'narrow')
        self.set_class(width < 80 or height < 24, 'too-small')
        self.query_one('#resize-note', Static).update('Please resize to at least 80 × 24. Saved configuration is retained.')

    def on_resize(self, event):
        if self.is_running and self.is_mounted:
            self.set_classes_for_size(event.size.width, event.size.height)

    def reload_registry(self):
        try:
            self.state = self.registry.read()
            self.registry_valid = True
            self.query_one('#registry-warning').display = False
        except RegistryError as error:
            self.registry_valid = False
            warning = self.query_one('#registry-warning', Static)
            warning.update(Text('REGISTRY UNAVAILABLE · displayed configuration may be stale. ' + str(error)))
            warning.display = True
        self.render_state()

    def render_state(self):
        if not self.is_running:
            return
        snapshot = self.health.snapshot(self.state['stores'])
        observations = {row['id']: row for row in snapshot['stores']}
        query = self.query_one('#store-search', Input).value.lower()
        table = self.query_one('#store-table', DataTable)
        table.clear()
        visible = [s for s in self.state['stores'] if query in (' '.join((s['id'], s['name'], s['country']))).lower()]
        for store in visible:
            status = observations[store['id']]['status']
            color = '#7de5ce' if status == 'SQL + OPA healthy' else '#ffc3bd' if status == 'Degraded' else '#ffe1a4' if status == 'Backend unassigned' else '#bfcee1'
            table.add_row(Text(store['name'] + ' / ' + store['country']), store['desired_state'], Text(status, style=color), key=store['id'])
        if visible:
            if self.selected not in {s['id'] for s in visible}:
                self.selected = visible[0]['id']
            table.move_cursor(row=next(i for i, s in enumerate(visible) if s['id'] == self.selected))
        self.render_detail(observations)
        health_table = self.query_one('#health-table', DataTable)
        health_table.clear()
        for row in snapshot['stores']:
            indicator = lambda value: 'OK' if value is True else 'FAIL' if value is False else '—'
            health_table.add_row(row['id'], indicator(row['database']), indicator(row['policy']), row['status'])
        activity = self.query_one('#activity-table', DataTable)
        activity.clear()
        for receipt in self.state['history'][-100:][::-1]:
            activity.add_row(str(receipt['revision']), receipt['action'], receipt['summary'], receipt['request_id'], key=str(receipt['revision']))
        self.query_one('#observability-summary', Static).update(Text(
            f"Desired: {self.state['observability']['desired_state']}\nObserved gateway report: {snapshot['observability']}\nExecution: adapter pending · saving intent does not change running services.\n"))
        resources = host_resources(self.registry.directory)
        self.query_one('#resources', Static).update(Text(
            f"CPU visibility: {resources['cpu_count']} logical CPUs\nDisk free: {size(resources['disk_free_bytes'])} of {size(resources['disk_total_bytes'])}\nAvailable memory: {size(resources['memory_available_bytes'])}\nShared host figures, not per-store capacity or reserved resources.\n"))
        self.update_status(snapshot)

    def render_detail(self, observations=None):
        store = next(s for s in self.state['stores'] if s['id'] == self.selected)
        observations = observations or {r['id']: r for r in self.health.snapshot(self.state['stores'])['stores']}
        row = observations[store['id']]
        self.query_one('#detail-title', Static).update(Text(store['name'] + '\n' + store['id']))
        self.query_one('#detail-body', Static).update(Text(
            f"Intended country: {store['country']} · geography unverified\nDesired: {store['desired_state']} · {store['node_count']} logical nodes\nObserved: {row['status']}\n{row['placement_note']}\nLogical node targets are unassigned. Save intent; deployment is deferred."))
        nodes = self.query_one('#node-table', DataTable)
        nodes.clear()
        for node in store['nodes']:
            nodes.add_row(node['id'], node['desired_state'], 'Unassigned')

    def update_status(self, snapshot=None):
        if not self.is_running:
            return
        snapshot = snapshot or self.health.snapshot(self.state['stores'])
        healthy = sum(row['status'] == 'SQL + OPA healthy' for row in snapshot['stores'])
        unassigned = sum(row['backend_assignment'] == 'unassigned' for row in snapshot['stores'])
        self.query_one('#metrics', Static).update(Text(
            f"{len(self.state['stores'])} STORES   {healthy} SQL/OPA HEALTHY   {unassigned} UNASSIGNED   REV {self.state['revision']}\n"
            f"Gateway: {snapshot['footprint']} · checked {stamp(snapshot['checked_at'])} · polling {'on' if self.auto_health else 'paused'}"))
        age = max(0, int(time.time() - snapshot['checked_at'])) if snapshot['checked_at'] else None
        self.query_one('#health-note', Static).update(Text(
            f"{'CURRENT' if snapshot['current'] else 'UNVERIFIED / STALE'} · age {str(age) + 's' if age is not None else 'unknown'} · last valid response {stamp(snapshot['last_success_at'])}\n"
            f"{snapshot['error'] or 'SQL/OPA reachability only; node liveness, placement and residency are not established.'}"))
        self.last_current = snapshot['current']

    @on(Input.Changed, '#store-search')
    def search_changed(self):
        if self.is_running and self.is_mounted and self.query_one('#store-table', DataTable).columns:
            self.render_state()

    @on(DataTable.RowHighlighted, '#store-table')
    def selected_row(self, event):
        # Queued cursor events can arrive while the default screen unmounts.
        if self.is_running and self.query('#detail-title') and event.row_key.value and any(s['id'] == event.row_key.value for s in self.state['stores']):
            self.selected = event.row_key.value
            self.render_detail()

    @on(DataTable.RowSelected, '#activity-table')
    def receipt_selected(self, event):
        receipt = next(r for r in self.state['history'] if str(r['revision']) == event.row_key.value)
        self.push_screen(Information('CONFIGURATION RECEIPT', '\n\n'.join(
            f'{key}: {receipt[key]}' for key in ('revision', 'at', 'action', 'summary', 'request_id')) + '\n\nConfiguration saved. Deployment adapter pending. This is not business SQL audit.'))

    def open_form(self, store=None, observability=False):
        if len(self.screen_stack) > 1:
            return
        self.reload_registry()
        if self.registry_valid:
            self.push_screen(Form(self.registry, store, observability), self.on_plan)

    def on_plan(self, plan):
        if plan:
            self.push_screen(Review(self.registry, plan), self.on_receipt)

    def on_receipt(self, receipt):
        self.reload_registry()
        if receipt:
            self.notify(f"Saved revision {receipt['revision']}. Deployment adapter pending.", title='Configuration receipt')

    def action_add_store(self):
        self.open_form()

    def action_configure_store(self):
        self.open_form(next(s for s in self.state['stores'] if s['id'] == self.selected))

    def action_observability(self):
        self.open_form(observability=True)

    def action_search(self):
        self.query_one('#tabs', TabbedContent).active = 'stores-tab'
        self.query_one('#store-search', Input).focus()

    def auto_refresh(self):
        if self.is_running and self.auto_health:
            self.action_refresh_health()

    def clock_tick(self):
        if not self.is_running or len(self.screen_stack) > 1:
            return
        current = self.health.snapshot(self.state['stores'])['current']
        if current != self.last_current:
            self.render_state()
        else:
            self.update_status()

    def action_refresh_health(self):
        if not self.is_running or self.polling:
            return
        self.polling = True
        self.reload_registry()
        self.poll_health()

    @work(thread=True)
    def poll_health(self):
        result = self.observer.poll()
        try:
            self.call_from_thread(self.accept_health, result)
        except RuntimeError:
            pass  # Terminal has already closed; there are no background mutations.

    def accept_health(self, result):
        self.polling = False
        if not self.is_running:
            return
        self.health.record(result)
        self.render_state()

    def action_pause_health(self):
        self.auto_health = not self.auto_health
        self.query_one('#pause-health', Button).label = 'Pause polling' if self.auto_health else 'Resume polling'
        self.update_status()

    def action_help(self):
        if len(self.screen_stack) == 1:
            self.push_screen(Information('ADMIN GUIDE',
                '1. Register a store, e.g. Germany / DE / STORE-DE-01.\n\n'
                '2. Review and save logical node identities. Physical targets remain unassigned.\n\n'
                '3. Configure desired node counts and state. Excess identities are retained.\n\n'
                '4. Observability intent is independent of SQL audit and live health polling.\n\n'
                '5. Live health comes only from the existing loopback lab gateway. New stores never inherit another store’s health.\n\n'
                'Configuration receipts persist outside managed SQL. No deploy, data-placement or infrastructure execution is implemented.'))

    @on(Button.Pressed)
    def main_buttons(self, event):
        actions = {'add-store': self.action_add_store, 'configure-store': self.action_configure_store,
                   'change-observability': self.action_observability, 'refresh-health': self.action_refresh_health,
                   'pause-health': self.action_pause_health}
        if event.button.id in actions:
            actions[event.button.id]()
