import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.services import shop_workspace_service
from app.state_store import tenant_scope


class ShopWorkspaceTests(unittest.TestCase):
    def test_commands_land_in_tenant_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_workspace_service.record_command("قیمت نزن")
                shop_workspace_service.record_command("از داخل پیجم مدل کیف‌ها رو بزار")
                shop_workspace_service.record_command("مانتو و شلوار را حذف کن")
                folder = shop_workspace_service.workspace_dir()
                self.assertTrue(folder.is_dir())
                self.assertTrue((folder / "commands.jsonl").is_file())
                text = shop_workspace_service.instructions_block()
                self.assertIn("قیمت روی کارت کالا نشان داده نشود", text)
                self.assertIn("از پیج", text)
                self.assertIn("نگو به پیج یا اینستاگرام دسترسی نداری", text)
                self.assertIn("مانتو", text)

    def test_edit_copies_site_files_into_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "site"
            (root / "lib").mkdir(parents=True)
            (root / "app").mkdir()
            (root / "lib" / "brand.ts").write_text("export const brand = { name: 'شهر کیف' }\n", encoding="utf-8")
            (root / "app" / "page.tsx").write_text("export default function Home() { return <h1>خانه</h1> }\n", encoding="utf-8")
            with patch.object(settings, "state_dir", raw), tenant_scope("09123456789"):
                shop_workspace_service.record_edit(
                    prompt="بنویس ویترین",
                    reply="متن عوض شد",
                    patched=True,
                    root=root,
                )
                copied = shop_workspace_service.workspace_dir() / "files" / "lib" / "brand.ts"
                self.assertTrue(copied.is_file())
                self.assertIn("شهر کیف", copied.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
