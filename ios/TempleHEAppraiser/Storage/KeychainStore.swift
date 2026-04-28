// ABOUTME: Keychain-backed storage for the access + refresh tokens (Phase 5 Sprint 1).
// ABOUTME: kSecAttrAccessibleWhenUnlockedThisDeviceOnly — never syncs across devices.

import Foundation
import Security

/// Thin wrapper over the Keychain for auth credentials. The accessibility class
/// is `WhenUnlockedThisDeviceOnly` so backups don't carry the tokens to a new
/// device — every install starts fresh and re-authenticates.
struct KeychainStore {
    enum Key: String {
        case accessToken = "templehe.accessToken"
        case refreshToken = "templehe.refreshToken"
    }

    enum KeychainError: Error {
        case unhandled(OSStatus)
    }

    private let service: String

    init(service: String = "com.templehe.appraiser") {
        self.service = service
    }

    // MARK: - Read / write

    func set(_ value: String?, for key: Key) throws {
        if let value = value {
            try save(value: value, for: key)
        } else {
            try delete(key: key)
        }
    }

    func get(_ key: Key) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key.rawValue,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnData as String: true,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    func clearAll() throws {
        try delete(key: .accessToken)
        try delete(key: .refreshToken)
    }

    // MARK: - Internals

    private func save(value: String, for key: Key) throws {
        guard let data = value.data(using: .utf8) else {
            throw KeychainError.unhandled(errSecParam)
        }
        // Delete-then-add is the simplest atomic update path; SecItemUpdate
        // requires a separate query without the value attributes which is
        // a footgun if the entry doesn't yet exist.
        try? delete(key: key)
        let attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key.rawValue,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.unhandled(status)
        }
    }

    private func delete(key: Key) throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key.rawValue,
        ]
        let status = SecItemDelete(query as CFDictionary)
        if status != errSecSuccess && status != errSecItemNotFound {
            throw KeychainError.unhandled(status)
        }
    }
}
