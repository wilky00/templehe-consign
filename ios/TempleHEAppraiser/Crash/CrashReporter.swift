// ABOUTME: Sentry iOS SDK integration — crash reporting + structured breadcrumbs.
// ABOUTME: Matches the API's Sentry project DSN family; no PII captured in breadcrumbs.

import Foundation

/// Initialise Sentry crash reporting.
///
/// Call ``start()`` once from ``App.init()`` before any UI is displayed.
/// The DSN is injected via the `SENTRY_DSN` build setting so it never
/// appears in source code (and differs between dev + prod schemes).
///
/// PII filtering: ``addBreadcrumb`` strips `user_id`, `email`, and `phone`
/// from any data dictionary before forwarding to the SDK so those values
/// never appear in Sentry event payloads.
enum CrashReporter {

    // Resolved from the active scheme's build settings at compile time.
    private static let dsn: String? = {
        Bundle.main.infoDictionary?["SENTRY_DSN"] as? String
    }()

    private static let environment: String = {
        #if DEBUG
        return "development"
        #else
        return "production"
        #endif
    }()

    /// Start Sentry. No-ops gracefully when the DSN is absent (e.g. local
    /// simulator runs without a configured `SENTRY_DSN` build setting).
    static func start() {
        guard let dsn, !dsn.isEmpty else {
            return
        }
        // When the Sentry iOS SDK is added via SPM, replace the body below
        // with the real initialisation block:
        //
        //   import Sentry
        //
        //   SentrySDK.start { options in
        //       options.dsn = dsn
        //       options.environment = environment
        //       options.beforeBreadcrumb = { crumb in
        //           Self.sanitise(crumb)
        //       }
        //       options.tracesSampleRate = 0.1
        //   }
        //
        // The method signature is intentionally left as a stub so the rest of
        // the app compiles without the SPM dependency present. Remove the
        // guard + this comment block once the SDK is added.
    }

    /// Attach a named breadcrumb with an arbitrary data payload.
    ///
    /// Strips PII keys (`user_id`, `email`, `phone`, `token`) before
    /// forwarding so the call site doesn't have to remember to redact.
    static func addBreadcrumb(message: String, data: [String: Any] = [:]) {
        let safe = sanitise(data)
        // Replace with SentrySDK.addBreadcrumb(crumb) once the SDK is present.
        _ = safe // suppress unused-variable warning until SDK lands.
    }

    // MARK: - Private

    private static let piiKeys: Set<String> = ["user_id", "email", "phone", "token"]

    private static func sanitise(_ data: [String: Any]) -> [String: Any] {
        data.filter { !piiKeys.contains($0.key) }
    }
}
