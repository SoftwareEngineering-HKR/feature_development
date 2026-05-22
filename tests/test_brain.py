"""
This file has been fully pair-programmed by Razmus and Marcus.
"""

import os
import sys
import unittest
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_final import Client

class TestClient(unittest.TestCase):

    def setUp(self):
        self.client = Client("127.0.0.1", 5007)

    def test_connect_postgres(self):
        self.assertTrue(hasattr(self.client, 'connect_to_postgres'))
        self.assertTrue(callable(getattr(self.client, 'connect_to_postgres')))

    def test_fetch_device_states_exists(self):
        self.assertTrue(hasattr(self.client, 'fetch_device_states'))
        self.assertTrue(callable(getattr(self.client, 'fetch_device_states')))

    def test_Openbci_exists(self):
        self.assertTrue(hasattr(self.client, 'Openbci'))
        self.assertTrue(callable(getattr(self.client, 'Openbci')))
    
    def test_mouse_exists(self):
        self.assertTrue(hasattr(self.client, 'mouse'))
        self.assertTrue(callable(getattr(self.client, 'mouse')))
    
    def test_handle_jaw_exists(self):
        self.assertTrue(hasattr(self.client, 'handle_jaw'))
        self.assertTrue(callable(getattr(self.client, 'handle_jaw')))

    def test_handle_talk_button_exists(self):
        self.assertTrue(hasattr(self.client, 'handle_talk_button'))
        self.assertTrue(callable(getattr(self.client, 'handle_talk_button')))

    def test_google_speech_recognition_exists(self):
        self.assertTrue(hasattr(self.client, 'google_speech_recognition'))
        self.assertTrue(callable(getattr(self.client, 'google_speech_recognition')))

    def test_pross_google_speech_recognition_exists(self):
        self.assertTrue(hasattr(self.client, 'pross_google_speech_recognition'))
        self.assertTrue(callable(getattr(self.client, 'pross_google_speech_recognition')))

    def test_handle_lock_exists(self):
        self.assertTrue(hasattr(self.client, 'handle_lock'))
        self.assertTrue(callable(getattr(self.client, 'handle_lock')))

    def test_login(self):
        self.assertTrue(hasattr(self.client, 'login'))
        self.assertTrue(callable(getattr(self.client, 'login')))

    def test_create_user(self):
        self.assertTrue(hasattr(self.client, 'create_user'))
        self.assertTrue(callable(getattr(self.client, 'create_user')))

    def test_validate_password(self):
        self.assertTrue(hasattr(self.client, 'validate_password'))
        self.assertTrue(callable(getattr(self.client, 'validate_password')))
    
    def test_validate_username(self):
        self.assertTrue(hasattr(self.client, 'validate_username'))
        self.assertTrue(callable(getattr(self.client, 'validate_username')))

    def test_validate_username_valid(self):
        result = self.client.validate_username("user_123")
        self.assertEqual(result, [])

    def test_validate_username_too_short(self):
        result = self.client.validate_username("ab")
        self.assertEqual(result, [
            "✗ At least 3 characters"
        ])

    def test_validate_username_invalid_characters(self):
        result = self.client.validate_username("user-1")
        self.assertEqual(result, [
            "✗ Only letters, numbers and underscore (_)"
        ])

    def test_validate_password_valid(self):
        result = self.client.validate_password("ValidPass1!")
        self.assertEqual(result, [])

    def test_validate_password_too_short(self):
        result = self.client.validate_password("Val1!")
        self.assertEqual(result, [
            "✗ At least 8 characters"
        ])

    def test_validate_password_missing_uppercase(self):
        result = self.client.validate_password("validpass1!")
        self.assertEqual(result, [
            "✗ At least one uppercase letter (A-Z)"
        ])

    def test_validate_password_missing_lowercase(self):
        result = self.client.validate_password("VALIDPASS1!")
        self.assertEqual(result, [
            "✗ At least one lowercase letter (a-z)"
        ])

    def test_validate_password_missing_digit(self):
        result = self.client.validate_password("ValidPass!")
        self.assertEqual(result, [
            "✗ At least one digit (0-9)"
        ])

    def test_validate_password_missing_special_character(self):
        result = self.client.validate_password("ValidPass1")
        self.assertEqual(result, [
            "✗ At least one special character (!@#$%^&*)"
        ])

        
if __name__ == '__main__':
    unittest.main()