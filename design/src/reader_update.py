"""Current reader journey, applied after historical component extensions."""
import re

reading_path = [
    ('index', 'Start here', 'The problem and a simple example'),
    ('entity-model', 'People, relationships & stores', 'Who owns the data and where it lives'),
    ('service-transactions', 'Business & sovereignty services', 'Keep existing services; govern location, reads and writes'),
    ('operational-model', 'What can be shared?', 'Minimal identity versus relationship details'),
    ('opa', 'How permission works', 'Why an exclusion wins over a grant'),
    ('federation', 'How data moves', 'Local success and remote delivery are different'),
    ('architecture', 'Inside the working lab', 'The components behind the example'),
    ('entity-migration', 'Moving the India entity', 'Changing location without two writers'),
    ('pilot-plan', 'Before a pilot', 'What still needs to be proved'),
]
by_slug = {p['slug']: p for p in pages}
historical_banners = [
    'Implementation status: three nodes, thirty entities',
    'New · executable entity relocation',
    'Operational isolation decision · edition 07',
    'Capacity & pilot assessment · 50M parties / 100M relationships',
    'Operational model extension · v3',
]
for p in pages:
    for title in historical_banners:
        p['body'] = re.sub(r'<aside class="callout"><strong>' + re.escape(title) +
                           r'</strong><p>.*?</p></aside>', '', p['body'], flags=re.S)
    p['kicker'] = 'Sovereign Federation Lab / Reader guide · edition 09'


def reader_section(anchor, title, body):
    return '<section class="doc-section" id="' + anchor + '"><h2>' + title + '</h2>' + body + '</section>'


status_key = reader_section('status', 'What is working, and what is proposed?', table(
    ['Label', 'What it means'], [
        ['Implemented lab', 'Real CockroachDB and OPA services on one Docker host. Container, policy, migration, restart, telemetry and browser gates have passed. Synthetic data only.'],
        ['Browser model', 'A simulation or illustration running in the browser. Its results do not prove database behaviour or capacity.'],
        ['Proposed pilot design', 'An intended extension that still needs implementation, testing or an approved bank decision.'],
    ]) + '<p>The lab has four separate single-node stores: Singapore, UK, US and Mumbai. '
    'It does not establish regional high availability, physical residency compliance, '
    '100M-record performance or erasure from backups. '
    '<a href="/guides/docs/CONTAINER_ACCEPTANCE.md">Read the executed acceptance evidence</a> '
    'or <a href="/design/development-lab.html#status">inspect the implementation matrix</a>.</p>')
glossary = reader_section('glossary', 'Words used in this guide', table(['Term', 'Plain meaning'], [
    ['Legal entity', 'A bank business with its own authority and access rules. Sharing a database does not merge those rules.'],
    ['Store', 'A database location where data is held. The entity-to-store mapping is separate from the entity identity.'],
    ['Business services', 'Existing banking services that own interactions, business rules and operational records.'],
    ['Sovereignty services', 'The supporting layer that governs approved placement, authority and policy-scoped movement.'],
    ['Routing', 'Selecting the current owner for a write or an approved source for a read. A route does not grant access.'],
    ['Party', 'A person or organisation. Minimal identity can be shared separately from its business relationships.'],
    ['Relationship', 'A particular business relationship owned by a legal entity, such as personal banking or a business account.'],
    ['Projection', 'The approved subset copied for a particular recipient; it is not a new owner record.'],
    ['Scope', 'The unit of policy and distribution: a minimal party identity or a connected relationship graph.'],
    ['Grant / exclusion', 'A permission to share / an explicit prohibition. A grant cannot override an exclusion or an invalid location.'],
    ['Authority / fence', 'The right to accept writes / a durable barrier that prevents an old writer accepting them.'],
    ['Snapshot / catch-up', 'A consistent starting copy / applying changes made while that copy was moving.'],
    ['Cutover', 'The controlled point where the new store becomes the writer after the source is fenced.'],
    ['Outbox / receipt', 'Durable work waiting to be delivered / evidence that a recipient accepted it.'],
    ['OPA / OpenTelemetry', 'The policy decision engine / instrumentation for traces, logs and metrics. Business audit remains separate and durable in SQL.'],
]))
journey = '<ol class="reading-path">' + ''.join(
    '<li><a href="' + slug + '.html">' + name + '</a><p>' + explanation + '</p></li>'
    for slug, name, explanation in reading_path[1:]) + '</ol>'
overview = by_slug['index']
overview['title'] = 'Share useful data. Respect each business’s boundaries.'
overview['summary'] = ('How can a bank serve the same person across legal entities without '
                       'sharing every relationship, every field or every location? This synthetic lab makes those choices visible.')
overview['body'] = reader_section('example', 'Start with one person and one relationship',
    '<p>A person has a banking relationship owned by a Singapore legal entity. An authorised '
    'UK entity needs selected information to service that relationship. The owner permits that '
    'use but explicitly excludes the US.</p>' + flow([
        ('Singapore owns the relationship', 'The owner commits the business change and records work to send an approved copy.'),
        ('UK receives selected fields', 'Policy checks both the recipient’s permission and the actual storage location before sending anything.'),
        ('US receives no relationship data', 'The explicit exclusion wins, even if another rule appears to allow sharing.'),
    ]) + '<p><strong>Identity is a separate question.</strong> For an eligible party, minimal identity '
    'may reach approved stores, including the US, under its own grants. That does not grant access '
    'to contacts, relationships or holdings. A party-level US exclusion blocks even the minimal identity.</p>') + \
    reader_section('boundaries', 'Three ideas to keep separate', table(['Question', 'Answer'], [
        ['Who owns this relationship?', 'A legal entity remains responsible for its business record and writes.'],
        ['Who may use which data?', 'Policy permits a particular recipient, purpose and subset of fields; exclusions narrow it.'],
        ['Where may the copy live?', 'The resolved physical store must satisfy the applicable location rules.'],
    ])) + reader_section('reading-path', 'Follow the explanation, then explore the details', journey) + \
    reader_section('try', 'See the example move',
        '<p>Open the <a href="' + MONITOR + '#generator">record generator</a>, choose '
        '<strong>sg-uk-no-us</strong>, and create a synthetic record. In the '
        '<a href="' + MONITOR + '#monitor">movement monitor</a>, follow its delivery to UK and its US exclusion. '
        'Then open <a href="' + MONITOR + '#services">business services</a> to compare party identity with relationship data.</p>'
        '<p>The hosted monitor uses a browser model. Run <code>./lab up</code> to use the real container lab; '
        'the monitor displays its mode. <a href="/design/development-lab.html">Use the run guide</a> when you are ready to start it.</p>') + \
    status_key + glossary
overview['prompt'] = ('Maintain the comprehension-first reader guide against the current repository. '
    'Preserve CockroachDB, OPA, the 30-entity catalog and all demonstrations. Explain the SG-owner, '
    'UK-recipient, US-exclusion example before schema or deployment details. Keep eligible minimal '
    'party distribution separate from relationship access. Label browser models and pilot proposals; '
    'link executed evidence and retain the single-host, migration-adapter and retained-storage limits. '
    'Verify the real-gateway reading path and document actual test results.')

entity = by_slug['entity-model']
entity['title'] = 'One person. Separate banking relationships.'
entity['summary'] = 'Knowing who someone is does not tell every bank entity what it may see or change.'
entity['body'] = (reader_section('example', 'The same person can have different relationships',
    '<p>Aster is a synthetic person with a personal banking relationship and a role in a business '
    'account. Each relationship has its own identity, owner and policy. Updating shared contact '
    'information does not make every recipient entitled to that information.</p>' + table([
        'Thing', 'Why it stays separate'], [
        ['Aster, the party', 'Identifies the person. An eligible minimal party copy contains only id, global_party_id and party_type.'],
        ['Personal relationship', 'Defines one business relationship and its permitted recipients and servicing data.'],
        ['Business relationship', 'Defines another relationship. Permissions are not inherited from personal banking.'],
        ['Holding', 'A product or account resource. A restriction can exclude this holding and its dependent rows.'],
    ])) + reader_section('entities-stores', 'A bank entity is not a database',
    '<p>The lab models 30 legal entities. Several can share a UK store while having different '
    'permissions. A recipient is selected by legal entity; its location is then resolved and '
    'checked separately. A nearby or shared database is never sufficient permission.</p>') + \
    reader_section('copies', 'A copy does not become a second owner',
    '<p>An approved UK projection retains source ownership. It can show selected fields, but '
    'it does not become a UK-owned master or inherit authority to accept writes. Two UK entities '
    'can receive different projections in the same store without overwriting one another.</p>') + \
    reader_section('keys', 'Technical detail: the current keys', table(['Object', 'Identity'], [
        ['Party', 'owner_entity_id + party id; global_party_id links identity without merging rights.'],
        ['Relationship', 'owner_entity_id + relationship id; several relationships for one party may coexist.'],
        ['Recipient graph', 'owner + scope + destination entity + business row id.'],
        ['Placement', 'entity_id → store_id + placement_version.'],
    ])) + '<details class="legacy-example"><summary>Separate teaching example: flat generated records</summary>' + \
    '<p>The generator also retains an older flat-record sandbox keyed by owner_entity_id + '
    'global_customer_id. It demonstrates movement and exclusions. This is not the normalized '
    'relationship key above; its record API should not be used as the operational model contract.</p></details>')
entity['prompt'] = ('Preserve the normalized business model and independent party/relationship scopes. '
    'Keep owner-qualified party and relationship UUIDs, shared identity without unioned rights, '
    'and recipient keys qualified by owner, scope, destination and business row. The retained '
    'flat owner/global_customer_id fixture is a separate demonstration. Test several relationships '
    'for one party, independent owners, eligible minimal party identity, recipient-specific fields '
    'and source-side exclusions in real CockroachDB/OPA. Do not add identity matching or merge/split '
    'governance without a separate approved scope.')

current_keys = table(['Layer', 'Current operational meaning'], [
    ['Party identity', 'global_party_id links a person or organisation; it does not union access rights.'],
    ['Relationship ownership', 'owner_entity_id + relationship id identifies independently governed business relationships.'],
    ['Projection', 'owner + scope + recipient entity + row id preserves the origin and the approved recipient.'],
    ['Placement', 'entity → versioned physical store; store.country is evaluated against applicable rules.'],
])
arch = by_slug['architecture']
arch['body'] = arch['body'].replace(model, current_keys).replace(
    'SG, GB and US independent CockroachDB single nodes',
    'Four independent CockroachDB single nodes: SG, UK, US and Mumbai (India migration)')
arch['body'] = reader_section('purpose', 'Each component answers one question', flow([
    ('Business API', 'What changed at the owner, and did its business data and audit commit?'),
    ('OPA policy engine', 'May this recipient receive these fields at the resolved location?'),
    ('Worker and recipient store', 'Has the approved copy actually arrived and been acknowledged?'),
    ('Monitor and telemetry', 'What happened, what remains pending, and what evidence can we inspect?'),
])) + arch['body']
arch['prompt'] = ('Continue from the validated four-store Docker lab and 30-entity catalog. '
    'Preserve separate CockroachDB single nodes, source/destination OPA admission, durable audit '
    'and the loopback gateway. The India migration fixture is separate from normalized business '
    'table migration. Treat regional HA, authenticated services and distributed fencing as bounded '
    'pilot extensions with new ADRs and real fault evidence; do not infer them from the local topology.')

context = by_slug['project-context']
context['title'] = 'Why this lab exists.'
context['summary'] = 'Explore useful sharing across bank businesses without treating identity, access and location as the same decision.'
context['body'] = (reader_section('problem', 'The problem',
    '<p>A bank may serve one person through many legal entities. Useful sharing must coexist '
    'with independent business ownership, access restrictions and approved storage locations. '
    'A universal customer copy or a geography switch alone cannot express those boundaries.</p>') + \
    reader_section('scope', 'What the demonstration answers',
    '<p>The lab shows approved minimal party identity, policy-scoped relationship data, source-side '
    'exclusions, acknowledged movement and a controlled India migration. Thirty synthetic entity '
    'mappings sit over three base stores; Mumbai is the fourth store for the isolated migration fixture.</p>') + \
    reader_section('limits', 'What remains an evaluation',
    '<p>This is a single-host experiment, not a connected bank estate. Regional identity, HA, '
    'distributed authority, normalized-table migration and large-scale performance remain pilot work. '
    'The original flat-record generator remains a separate teaching example.</p>') + \
    '<p><a href="index.html#reading-path">Follow the reader guide</a> or '
    '<a href="/guides/docs/CONTAINER_ACCEPTANCE.md">inspect acceptance evidence</a>.</p>')
context['prompt'] = overview['prompt']

# Replace obsolete execution claims, retaining the reference trail and limitations.
references = by_slug['references']
references['body'] = reader_section('evidence', 'Start with inspectable evidence',
    '<p><a href="/guides/docs/CONTAINER_ACCEPTANCE.md">Container acceptance report</a>: '
    'executed real SQL/OPA placement, migration, restart, telemetry and live browser gates. '
    '<a href="/guides/TESTING.md">Testing guide</a>: commands and the distinction between '
    'container acceptance, source tests and browser models. '
    '<a href="/design/adr-register.html">Decision register</a>: choices, alternatives and pilot gates.</p>') + \
    reader_section('assumptions', 'Synthetic assumptions are not bank policy',
    '<p>All entity names, country allocations, local-only rules and hub mappings are examples. '
    'The four stores run on one host. Country labels do not prove physical residency. '
    'Browser model results and historical SQLite unit tests do not establish CockroachDB behaviour.</p>') + \
    reader_section('sources', 'Primary platform references', sources([
        ('OPA policy language', 'https://www.openpolicyagent.org/docs/policy-language'),
        ('CockroachDB data domiciling', 'https://www.cockroachlabs.com/docs/stable/data-domiciling'),
        ('CockroachDB transaction retries', 'https://www.cockroachlabs.com/docs/stable/transaction-retry-error-reference'),
        ('OpenTelemetry sensitive data guidance', 'https://opentelemetry.io/docs/security/handling-sensitive-data/'),
        ('Natural Earth map provenance', 'https://www.naturalearthdata.com/about/terms-of-use/'),
    ]))
by_slug['engineering']['summary'] = 'Continue from the validated container lab; earn each pilot capability with its own acceptance evidence.'
by_slug['engineering']['prompt'] = arch['prompt'] + (' Prioritise database crash and partition '
    'recovery, recipient-commit/source-ack gaps and migration authority boundaries. Run the existing '
    'acceptance gates and report failures without skipping assertions. Add normalized-table '
    'migration and regional identity/TLS only as separately scoped changes.')
for slug in ['federation', 'transactions', 'apis']:
    by_slug[slug]['body'] = ('<p class="legacy-note">The flat record API and envelope examples below are a separate teaching fixture. '
        'Use the <a href="operational-model.html">operational model</a> for party and relationship scopes; '
        'the flat owner/customer key is not the normalized relationship key.</p>' + by_slug[slug]['body'])

explanations = {
    'operational-model': reader_section('example', 'Recognising a person is different from sharing their account',
        '<p>In the seed example, an approved US recipient can recognise Aster from three minimal '
        'party fields. It receives no personal relationship, contact details or holdings. A UK '
        'recipient may receive selected relationship information under a separate servicing grant. '
        'If Aster’s party identity is excluded from the US, even the minimal copy is removed.</p>'
        '<p>The tables and diagram below show how that distinction is represented. You can also '
        '<a href="' + MONITOR + '#services">compare the two paths in business services</a>.</p>'),
    'opa': reader_section('example', 'Permission has to answer all three questions', flow([
        ('Is the recipient allowed?', 'A UK servicing grant names a particular legal entity, not every entity in its store.'),
        ('Is this location allowed?', 'A recipient mapped to a US store fails if the relationship excludes the US.'),
        ('Are these fields allowed?', 'An approved purpose and profile still limit what can be copied.'),
    ]) + '<p>OPA is the engine that evaluates these rules. The application enforces the result. '
        'If it cannot obtain the mandatory decision, it refuses the crossing; it does not guess.</p>'),
    'federation': reader_section('example', 'A successful update is not the same as a delivered copy',
        '<p>Singapore first commits the business change, its audit and the work needed for delivery. '
        'The worker then checks permission and sends only an approved subset to UK. UK checks again '
        'and acknowledges its own database commit. The monitor distinguishes queued work, stored '
        'copies and acknowledgements.</p><p>If UK is paused, the owner update can succeed while '
        'delivery remains pending. If UK access is revoked, reads are denied and deletion may remain '
        'pending until the store returns. A stored copy and current permission are different facts.</p>'),
    'entity-migration': reader_section('example', 'Move the data, then change who may write',
        '<p>The India example starts with Singapore as the writer. Mumbai receives a starting copy '
        'while Singapore continues accepting changes. Catch-up brings the copy up to date. Validation '
        'checks it; a durable source fence then stops Singapore writes before Mumbai becomes the writer.</p>'
        '<p>Old writers are rejected, and cleanup removes the old live rows. This demonstration moves '
        'an isolated synthetic migration fixture, not the existing normalized business tables. '
        'Completing cleanup does not erase database history or backups.</p>'),
    'pilot-plan': reader_section('purpose', 'Passing the lab earns the next tests',
        '<p>The single-host lab demonstrates the core sharing and authority rules. A bank pilot still '
        'needs authenticated regional services, crash and partition recovery, migration of normalized '
        'tables, approved placement and retention, and measured capacity. The backlog below separates '
        'these decisions and their required evidence.</p>'),
}
for slug, explanation in explanations.items():
    by_slug[slug]['body'] = explanation + by_slug[slug]['body']

exec((ROOT/'src/service_reader_update.py').read_text())

# The decision page distinguishes the original planner from the working migration slice.
by_slug['decisions']['body'] = by_slug['decisions']['body'].replace(
    '<td>Impact simulation only</td>', '<td>Read-only catalog planner plus isolated executed India migration</td>')

# Keep mixed technical pages explicit without a stack of release announcements.
proposals = {'platform', 'gateways', 'service-transactions', 'performance-scale', 'work-isolation', 'pilot-plan'}
models = {'control-plane', 'policy-lab', 'operations'}
for p in pages:
    if p['slug'] in proposals:
        label = 'Proposed pilot design'
        explanation = 'This page describes a target design. The local lab and browser models demonstrate bounded subsets; the proposal is not production acceptance.'
    elif p['slug'] in models:
        label = 'Browser model'
        explanation = 'These illustrations explain the decisions. Use the monitor in live container mode and the acceptance report for executed service evidence.'
    else:
        label = 'Implemented lab'
        explanation = 'The synthetic container lab is validated. Technical extension points on this page remain proposals unless explicitly identified as implemented.'
    p['reader_status'] = '<details class="reader-status"><summary>' + label + '</summary><p>' + explanation + \
        ' <a href="index.html#status">Understand the labels</a>.</p></details>'
    if p['slug'] != 'index':
        p['body'] = '<p class="reader-help"><a href="index.html#reading-path">Start with the example</a> · ' + \
            '<a href="index.html#glossary">Look up a term</a></p>' + p['body']
    if p['slug'] != 'index':
        p['body'] = p['reader_status'] + p['body']
    p['prompt'] = p['prompt'].replace(intro, '')
    if p['slug'] in [entry[0] for entry in reading_path]:
        position = [entry[0] for entry in reading_path].index(p['slug'])
        neighbours = []
        if position:
            slug, name, _ = reading_path[position - 1]
            neighbours.append('<a rel="prev" href="' + slug + '.html">← Previous: ' + name + '</a>')
        if position + 1 < len(reading_path):
            slug, name, _ = reading_path[position + 1]
            neighbours.append('<a rel="next" href="' + slug + '.html">Next: ' + name + ' →</a>')
        p['body'] += '<nav class="reading-links" aria-label="Reader journey">' + ''.join(neighbours) + '</nav>'
