# "OBI Energy Tracker" - HACS Integration
This integration allows you to monitor your **OBI Energy Tracker** device directly within Home Assistant. The OBI Energy Tracker is a cost-effective solution for reading smart energy meters, typically accessed via the heyOBI smartphone application.e.

## Installation

Add this repository, via custom repository: https://www.hacs.xyz/docs/faq/custom_repositories/

## OBI Energy Tracker

<img src="https://bilder.obi.de/d9c6b340-b37f-48fd-92f2-72114bad03ad/prZZK/image.jpeg" width="200" alt="Energy Tracker Device">

The "OBI Energy Tracker" is a low cost device to read out smart energy meters. In default you can access the data in the "heyOBI" application on our smartphone.
I extracted the API Calls from the backend of the application, and created this "Home Assistant" Integration. 

## Configuration

During setup, you'll need:
- **Email**: Your "OBI" account email address
- **Password**: Your "OBI" account password
- **Country**: Country code (default: `DE`)

## Power endpoint probe

After configuring the integration, call the Home Assistant service
`obi_energy_tracker.probe_power_endpoints` with the integration's `entry_id`.
It tests the known OBI Cloud endpoints and measures with the existing JWT login.
Each request URL, query parameters, status and complete response body is available
only when debug logging for `custom_components.obi_energy_tracker` is enabled.

When a valid power source is found, the integration reloads and adds a `Power`
sensor in watts. The generic `obi_energy_tracker.debug_get` service can be used
to test another relative API path; it requires `entry_id`, `path`, and optionally
`params`. Absolute URLs and query strings in `path` are rejected.

## API Details & Credits

---

*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*
