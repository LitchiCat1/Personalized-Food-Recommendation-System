import os
import unittest
from unittest.mock import patch

from services.auth_service import is_auth_required, is_supabase_auth_configured


class AuthServiceConfigurationTests(unittest.TestCase):
    def test_render_defaults_to_required_auth(self):
        with patch.dict(os.environ, {"RENDER": "true"}, clear=True):
            self.assertTrue(is_auth_required())

    def test_explicit_auth_flag_overrides_render_default(self):
        with patch.dict(os.environ, {"RENDER": "true", "SUPABASE_AUTH_REQUIRED": "false"}, clear=True):
            self.assertFalse(is_auth_required())

    def test_supabase_configuration_requires_url_and_publishable_key(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://project.supabase.co"}, clear=True):
            self.assertFalse(is_supabase_auth_configured())
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "publishable-key",
        }, clear=True):
            self.assertTrue(is_supabase_auth_configured())


if __name__ == "__main__":
    unittest.main()
