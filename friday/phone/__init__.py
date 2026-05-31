"""FRIDAY's phone-call assistant subsystem.

Modules:
- ``call_planner`` — turns a plain-English request into a structured ``CallBrief``.
- ``drivers`` — ``PhoneDriver`` ABC + ``SimulatedPhoneDriver`` (Ollama roleplay)
  + ``TwilioPhoneDriver`` scaffold for opt-in live telephony.
- ``manager`` — ``PhoneCallManager`` coordinates planner → driver → events → log.
"""
