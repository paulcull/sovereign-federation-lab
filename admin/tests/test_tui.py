"""Real Textual driver tests; controlled health responses are UI evidence only."""
import tempfile
import time
import unittest
import uuid

from textual.widgets import DataTable, Input, Select, Static, TabbedContent

from admin.health import Observation
from admin.registry import Registry
from admin.tui import AdminApp, Form, Review


class ControlledObserver:
    def poll(self):
        return Observation(time.time(), True, footprint='mdm-compact', observability='suspended',
            regions={'SG': {'database': True, 'policy': True}, 'UK': {'database': True, 'policy': True}})


class TUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.registry = Registry(self.folder.name)

    async def register(self, app, pilot, sid='STORE-DE-01', name='Germany'):
        await pilot.press('a')
        await pilot.pause()
        self.assertIsInstance(app.screen, Form)
        app.screen.query_one('#store-id', Input).value = sid
        app.screen.query_one('#store-name', Input).value = name
        app.screen.query_one('#country', Input).value = 'DE'
        app.screen.query_one('#node-count', Input).value = '3'
        await pilot.click('#review-form')
        await pilot.pause()
        self.assertIsInstance(app.screen, Review)

    async def test_register_review_save_filter_resize_and_reload(self):
        app = AdminApp(self.registry, ControlledObserver(), auto_health=False)
        async with app.run_test(size=(140, 42)) as pilot:
            await self.register(app, pilot)
            await pilot.click('#save-review')
            await pilot.pause()
            self.assertEqual(self.registry.read()['revision'], 1)
            await pilot.press('/')
            app.query_one('#store-search', Input).value = 'Germany'
            await pilot.pause()
            self.assertEqual(app.query_one('#store-table', DataTable).row_count, 1)
            self.assertEqual(app.selected, 'STORE-DE-01')
            self.assertEqual(app.query_one('#node-table', DataTable).row_count, 3)
            self.assertIn('Backend unassigned', str(app.query_one('#detail-body', Static).render()))
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            self.assertTrue(app.has_class('narrow'))
            self.assertFalse(app.has_class('too-small'))
            await pilot.resize_terminal(60, 20)
            self.assertTrue(app.has_class('too-small'))
        fresh = AdminApp(Registry(self.folder.name), ControlledObserver(), auto_health=False)
        async with fresh.run_test(size=(80, 24)) as pilot:
            self.assertEqual(fresh.state['stores'][-1]['id'], 'STORE-DE-01')

    async def test_cancel_invalid_form_and_stale_review(self):
        app = AdminApp(self.registry, ControlledObserver(), auto_health=False)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.press('a')
            await pilot.click('#review-form')
            self.assertIsInstance(app.screen, Form)
            self.assertNotEqual(str(app.screen.query_one('#form-error', Static).render()), '')
            await pilot.press('escape')
            self.assertEqual(self.registry.read()['revision'], 0)
            await self.register(app, pilot)
            self.registry.save(self.registry.plan('observability', {'desired_state': 'suspended'}), str(uuid.uuid4()))
            await pilot.click('#save-review')
            self.assertIsInstance(app.screen, Review)
            self.assertTrue(app.screen.query_one('#save-review').disabled)
            self.assertIn('since review', str(app.screen.query_one('#review-error', Static).render()))
            await pilot.press('escape')
            self.assertEqual(len(self.registry.read()['stores']), 4)

    async def test_configure_nodes_observability_activity_and_health_during_modal(self):
        app = AdminApp(self.registry, ControlledObserver(), auto_health=False)
        async with app.run_test(size=(140, 42)) as pilot:
            await self.register(app, pilot)
            app.accept_health(ControlledObserver().poll())
            self.assertIsInstance(app.screen, Review)
            await pilot.click('#save-review')
            app.query_one('#store-search', Input).value = 'Germany'
            await pilot.pause()
            app.query_one('#store-table', DataTable).focus()
            await pilot.press('e')
            app.screen.query_one('#node-count', Input).value = '1'
            await pilot.click('#review-form')
            await pilot.click('#save-review')
            self.assertEqual(self.registry.read()['stores'][-1]['nodes'][2]['desired_state'], 'suspended')
            await pilot.press('o')
            app.screen.query_one('#desired-state', Select).value = 'suspended'
            await pilot.click('#review-form')
            await pilot.click('#save-review')
            self.assertEqual(self.registry.read()['observability']['desired_state'], 'suspended')
            app.query_one('#tabs', TabbedContent).active = 'activity-tab'
            await pilot.pause()
            self.assertEqual(app.query_one('#activity-table', DataTable).row_count, 3)
            app.query_one('#tabs', TabbedContent).active = 'health-tab'
            app.accept_health(Observation(time.time() + .01, False, error='gateway_unavailable'))
            await pilot.pause()
            self.assertIn('UNVERIFIED', str(app.query_one('#health-note', Static).render()))
            self.assertEqual(self.registry.read()['revision'], 3)


if __name__ == '__main__':unittest.main()
