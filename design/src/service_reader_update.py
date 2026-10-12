"""Explain reuse and routing before the retained engineering contracts."""
service_roles = table(['Responsibility', 'Business services', 'Sovereignty services'], [
    ['Purpose', 'Own banking interactions, business rules and operational records.',
     'Govern approved data location, write authority and policy-scoped copies.'],
    ['Facts and decisions', 'Supply ownership, relationship context, consent and classification facts.',
     'Combine trusted facts with grants, exclusions and placement; OPA evaluates the applicable rules.'],
    ['Change', 'Validate a command and commit its business effect, mandatory audit and export intent locally.',
     'Deliver approved copies asynchronously; track receipts, restrictions and live-copy cleanup.'],
    ['Access', 'Serve the approved business view and enforce the caller’s permitted action and purpose.',
     'Supply current placement and authority checks; guard imports and projection reads.'],
])
service_intro = reader_section('services', 'Keep the banking services you already have',
    '<p><strong>Business services manage banking interactions. Sovereignty services govern '
    'where the data may live and how approved copies move.</strong> Party, relationship, '
    'contact and holdings services may already exist. Reuse their APIs, business rules and '
    'data ownership; add the integration needed for the data they share.</p>'
    '<p>These are responsibility boundaries. In this lab, business modules and sovereignty '
    'coordination share one FastAPI harness, with separate OPA processes. Independent regional '
    'peers and automatic routing are a proposed pilot design.</p>'
    '<p><a href="service-transactions.html">Follow an update through both responsibilities</a>, '
    'including read and write routing.</p>')
overview['body'] = overview['body'].replace(
    '<section class="doc-section" id="boundaries">', service_intro +
    '<section class="doc-section" id="boundaries">', 1)

services = by_slug['service-transactions']
technical_contracts = services['body']
services['title'] = 'Keep business services. Add governed federation.'
services['summary'] = ('Reuse existing banking services. A loosely coupled sovereignty layer '
                       'governs location and movement; business services retain the interactions.')
services['body'] = (
    reader_section('responsibilities', 'Two responsibilities, working together',
        '<p>Start with the services already running in the bank. A contact service still '
        'updates contact information; a holdings service still applies its product rules. '
        'The sovereignty layer supplies placement and authority decisions and manages approved '
        'copies. The receiving business service uses a permitted view; a copy never becomes '
        'a second master.</p>' + service_roles) +
    reader_section('peers', 'Deploy peers alongside participating services',
        '<p><strong>Proposed pilot design.</strong> Deploy the same sovereignty component '
        'in each approved region that participates in sharing. Configure its entity/store '
        'bindings, local policy and narrow service credentials. Each peer connects to existing '
        'business services through adapters and to other peers through private authenticated '
        'export/import endpoints. A peer may support several services or entities; sharing '
        'a deployment never merges their permissions.</p>' + flow([
            ('Existing business service', 'Keeps its API, interactions and authoritative banking records.'),
            ('Local sovereignty peer', 'Resolves approved placement and governs export, import and current authority.'),
            ('Approved recipient peer', 'Accepts a permitted projection for the recipient business service.'),
        ]) + '<p>The normalized lab schema illustrates these contracts. Map existing business '
        'keys and relationships through an adapter; adopting the example tables or consolidating '
        'all business services is not a prerequisite. The lab does not yet supply a generic '
        'peer installer or integrations for an existing bank estate.</p>') +
    reader_section('integration', 'Integrate only where the service participates', table(
        ['Participation', 'Required integration'], [
            ['No governed shared data', 'No federation adapter is needed. Existing authentication, local controls and any applicable residency obligations still apply.'],
            ['Read a shared view', 'Use an authorised query adapter that checks recipient, purpose, current policy and approved location before returning the projection.'],
            ['Create or change shared data', 'Reuse a compatible transactional outbox or add a local transaction hook for resource bindings, versions, export intent and mandatory audit. Cover every writer of that governed data.'],
            ['Bulk loads, direct SQL or maintenance', 'Use the same governed mutation contract or restrict write credentials. Unregistered changes must not silently bypass the controls.'],
        ]) + '<p><strong>Loose coupling does not mean zero integration.</strong> Local business '
        'commit and remote delivery are separate. The local hook shares the existing transaction; '
        'it does not call a remote sovereignty service while that transaction is open. An existing '
        'event stream is reusable only if it preserves the required atomic intent, ownership, '
        'scope and version information. A raw changefeed alone does not establish that contract.</p>'
        '<p>Business APIs and workflows remain with their services. The adapter boundary contains '
        'placement lookup, local mutation intent, guarded query and approved import/export. '
        'See <a href="sovereignty-integration.html">the detailed integration contract</a>.</p>') +
    reader_section('routing', 'Read and write routing answer different questions',
        '<p>The gateway or service adapter selects a route using trusted ownership and a '
        'versioned placement directory supplied by the sovereignty layer. Business services '
        'execute the interaction. <strong>A route does not grant access.</strong> Check caller, '
        'recipient, purpose, fields and processing location as well as storage location; moving '
        'a request body through a prohibited region is already a prohibited crossing.</p>' + table(
            ['Request', 'Where it goes', 'What must hold'], [
                ['Write a relationship or holding', 'The current authoritative owner’s business service.', 'Business validation, current writer authority and a permitted processing path. A recipient projection is not writable as the owner.'],
                ['Read an approved local view', 'The recipient’s business service over its local projection.', 'Current permission and placement, approved fields, and freshness acceptable to that business interaction. A stored copy alone is insufficient.'],
                ['Read requiring the latest committed business state', 'The owner service, only when that processing path is permitted.', 'Authorisation and an explicit freshness requirement. If a lawful fresh read is unavailable, report unavailable or pending; do not widen access.'],
                ['Write after an entity migration', 'The new owner location after fenced cutover.', 'Refresh the verified placement and authority version. The old writer rejects stale requests even if a router cached the old address.'],
            ]) + '<p>No nearest-store fallback, automatic writer promotion or unrestricted '
        'cross-region read fan-out is implied. Unknown authority or missing mandatory policy '
        'fails closed for the affected operation. A replica or telemetry outage need not undo '
        'a valid owner commit; required authority checks and transactional audit remain mandatory.</p>') +
    reader_section('contact-update', 'Follow one Singapore contact update', flow([
        ('Route the command', 'An authorised UK interaction resolves the Singapore owner and uses an explicitly permitted processing path.'),
        ('Commit at the owner', 'The Singapore business service applies its rules and commits contact, versions, export intent and audit together.'),
        ('Move the approved view', 'The source peer enforces exclusions before export; UK rechecks and commits only the allowed copy. US receives no excluded relationship data.'),
        ('Read with an explicit need', 'A UK service can use its permitted local view when freshness allows. A read requiring the latest state uses a lawful owner path or reports pending/unavailable.'),
    ]) + '<p>Minimal party identity has its own eligibility and grants. Its presence in the US '
        'does not permit a US relationship read or write.</p>') +
    reader_section('implementation', 'What the lab proves, and what the pilot must add',
        '<p>The real container lab proves local SQL business/outbox/audit commits, OPA-scoped '
        'projections and guarded recipient reads. Those reads check current policy and placement '
        'but can return an older ordinary data version. They consult owner authority; there is '
        'no offline authority lease or automatic owner-read fallback.</p><p>The isolated India '
        'migration proves source fencing and stale-write rejection for its separate fixture. '
        'Migration of normalized business tables, independent peer deployment, authenticated '
        'routing, an API freshness contract and distributed authority remain pilot work. '
        '<a href="/design/ADR-0017.html">Read the proposed integration and routing decision</a> '
        'or <a href="/guides/docs/SERVICE_GUIDE_REVIEW.md">inspect this guide’s executed checks</a>.</p>') +
    '<details class="legacy-example"><summary>Technical reference: local transactions and API contracts</summary>' +
    technical_contracts + '</details>')
services['prompt'] = ('Extend existing banking services through bounded adapters; preserve their '
    'business APIs and ownership. Treat independent sovereignty peers and authenticated routing '
    'as pilot work. Integrate writers of governed shared data with a compatible atomic outbox '
    'or local hook, durable audit and current versions. Enforce source exclusions, guarded '
    'recipient reads, permitted processing paths, explicit freshness and fenced owner writes. '
    'Do not require estate-wide service consolidation, a new banking master or remote calls '
    'inside the owner transaction. Preserve and run the real CockroachDB/OPA lab acceptance gates.')

arch['body'] = reader_section('service-boundaries', 'Responsibility is separate from deployment',
    '<p>Business services own banking interactions. Sovereignty services govern approved '
    'location, authority and movement. The single harness makes these responsibilities testable '
    'in the lab; it is not evidence of independently deployed regional peers.</p>'
    '<p>Reuse existing business services and integrate participating data through adapters. '
    '<a href="service-transactions.html#routing">Read and write routing</a> distinguishes '
    'the current writer from an approved local read view.</p>') + arch['body']
integration_page = by_slug['sovereignty-integration']
integration_page['body'] = reader_section('existing-services', 'Start with the existing service contract',
    '<p>Keep the banking API and business ownership. Integrate services that read or mutate '
    'governed shared data through a query adapter and, for writers, a compatible transactional '
    'outbox or local hook. Services outside that sharing path need no federation adapter. '
    'The tables below illustrate the lab adapter contract; they do not require every existing '
    'service to adopt this schema. <a href="service-transactions.html#integration">Choose the '
    'integration needed</a> before the table details.</p>') + integration_page['body']
gateway_page = by_slug['gateways']
gateway_page['body'] = reader_section('read-write-routing', 'Select the service, then enforce its permissions',
    '<p><strong>Proposed pilot design.</strong> A gateway or existing service adapter consumes '
    'trusted placement decisions from the sovereignty layer. Writes target the current owner; '
    'reads can use an authorised recipient view with suitable freshness. Business services '
    'continue to execute their APIs and rules. The handler revalidates authority and permissions; '
    'a cached route never makes an old writer valid after cutover.</p>'
    '<p>The loopback lab gateway proxies one harness. It does not implement distributed '
    'read/write routing. <a href="service-transactions.html#routing">Follow the routing explanation</a>.</p>') + gateway_page['body']
