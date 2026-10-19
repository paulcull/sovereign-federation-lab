"""Capture the real TUI with actual gateway observations; creates no saved intent."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from textual.widgets import TabbedContent
from admin.health import GatewayObserver
from admin.registry import Registry
from admin.tui import AdminApp


async def capture(folder, state_dir):
    folder.mkdir(parents=True, exist_ok=True)
    app = AdminApp(Registry(state_dir), GatewayObserver(), auto_health=False)
    async with app.run_test(size=(140, 42)) as pilot:
        app.accept_health(await asyncio.to_thread(app.observer.poll))
        if any(s['id'] == 'STORE-DE-01' for s in app.state['stores']):
            app.selected = 'STORE-DE-01'
            app.render_state()
        for tab in ['stores', 'health', 'environment', 'activity']:
            await pilot.click('#--content-tab-' + tab + '-tab')
            await pilot.pause()
            assert app.query_one('#tabs', TabbedContent).active == tab + '-tab'
            app.save_screenshot(tab + '.svg', path=str(folder))
        await pilot.click('#--content-tab-stores-tab')
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        app.save_screenshot('stores-80x24.svg', path=str(folder))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/admin-screens')
    parser.add_argument('--state-dir', default='.lab-admin')
    args = parser.parse_args()
    asyncio.run(capture(Path(args.output), args.state_dir))
