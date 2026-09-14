-- Fictional seed data. Every person, department and asset here is invented.

INSERT INTO departments (department_id, name, site, clinical) VALUES
    ('EMERG', 'Emergency Department',            'Foothills General',    1),
    ('ICU',   'Intensive Care Unit',             'Foothills General',    1),
    ('MED4B', 'Unit 4B Internal Medicine',       'Foothills General',    1),
    ('PHARM', 'Pharmacy',                        'Foothills General',    1),
    ('LAB',   'Laboratory Services',             'Riverside Lab Centre', 1),
    ('DI',    'Diagnostic Imaging',              'Foothills General',    1),
    ('FIN',   'Finance',                         'Corporate Office',     0),
    ('HR',    'People and Culture',              'Corporate Office',     0),
    ('ITS',   'Information Technology Services', 'Corporate Office',     0);

INSERT INTO services (service_id, name, criticality) VALUES
    ('emr',                   'Electronic Medical Record',     'high'),
    ('lis',                   'Laboratory Information System', 'high'),
    ('pacs',                  'Imaging Archive (PACS)',        'high'),
    ('pharmacy_dispensing',   'Pharmacy Dispensing',           'high'),
    ('clinical_device_fleet', 'Clinical Device Fleet',         'high'),
    ('wireless',              'Wireless Network',              'high'),
    ('remote_access',         'Remote Access VPN',             'medium'),
    ('email_calendar',        'Email and Calendar',            'medium'),
    ('end_user_computing',    'End-User Computing',            'medium'),
    ('finance_erp',           'Finance ERP',                   'medium'),
    ('office_printing',       'Office Printing',               'low'),
    ('hr_portal',             'HR Self-Service Portal',        'low');

INSERT INTO department_services (department_id, service_id) VALUES
    ('EMERG', 'emr'), ('EMERG', 'clinical_device_fleet'), ('EMERG', 'wireless'),
    ('EMERG', 'email_calendar'), ('EMERG', 'end_user_computing'),
    ('ICU', 'emr'), ('ICU', 'clinical_device_fleet'), ('ICU', 'wireless'),
    ('ICU', 'email_calendar'), ('ICU', 'end_user_computing'),
    ('MED4B', 'emr'), ('MED4B', 'clinical_device_fleet'), ('MED4B', 'wireless'),
    ('MED4B', 'email_calendar'), ('MED4B', 'end_user_computing'), ('MED4B', 'office_printing'),
    ('PHARM', 'emr'), ('PHARM', 'pharmacy_dispensing'), ('PHARM', 'email_calendar'),
    ('PHARM', 'end_user_computing'), ('PHARM', 'office_printing'),
    ('LAB', 'lis'), ('LAB', 'emr'), ('LAB', 'email_calendar'), ('LAB', 'end_user_computing'),
    ('DI', 'pacs'), ('DI', 'emr'), ('DI', 'email_calendar'), ('DI', 'end_user_computing'),
    ('FIN', 'finance_erp'), ('FIN', 'remote_access'), ('FIN', 'email_calendar'),
    ('FIN', 'end_user_computing'), ('FIN', 'office_printing'), ('FIN', 'hr_portal'),
    ('HR', 'hr_portal'), ('HR', 'remote_access'), ('HR', 'email_calendar'),
    ('HR', 'end_user_computing'), ('HR', 'office_printing'),
    ('ITS', 'remote_access'), ('ITS', 'email_calendar'), ('ITS', 'end_user_computing');

INSERT INTO employees (employee_id, full_name, email, department_id, role) VALUES
    ('E100101', 'Dana Whitfield',  'dana.whitfield@contoso.example',  'EMERG', 'Registered Nurse'),
    ('E100102', 'Marcus Oyelaran', 'marcus.oyelaran@contoso.example', 'EMERG', 'Emergency Physician'),
    ('E100201', 'Priya Raman',     'priya.raman@contoso.example',     'ICU',   'Charge Nurse'),
    ('E100202', 'Tomas Lindqvist', 'tomas.lindqvist@contoso.example', 'ICU',   'Respiratory Therapist'),
    ('E100301', 'Grace Okafor',    'grace.okafor@contoso.example',    'MED4B', 'Unit Clerk'),
    ('E100302', 'Liam Chen',       'liam.chen@contoso.example',       'MED4B', 'Registered Nurse'),
    ('E100401', 'Sofia Marchetti', 'sofia.marchetti@contoso.example', 'PHARM', 'Pharmacist'),
    ('E100501', 'Ahmed Haddad',    'ahmed.haddad@contoso.example',    'LAB',   'Medical Laboratory Technologist'),
    ('E100601', 'Hannah Brooks',   'hannah.brooks@contoso.example',   'DI',    'Radiologist'),
    ('E100701', 'Kevin Nguyen',    'kevin.nguyen@contoso.example',    'FIN',   'Financial Analyst'),
    ('E100702', 'Rebecca Stone',   'rebecca.stone@contoso.example',   'FIN',   'Payroll Specialist'),
    ('E100801', 'Olivia Grant',    'olivia.grant@contoso.example',    'HR',    'HR Advisor'),
    ('E100901', 'Samir Patel',     'samir.patel@contoso.example',     'ITS',   'Service Desk Analyst');

INSERT INTO assets (asset_tag, asset_type, model, service_id, assigned_to) VALUES
    ('CH-LT-00042',  'laptop',                'Laptop 14in',            'end_user_computing',    'E100701'),
    ('CH-LT-00043',  'laptop',                'Laptop 14in',            'end_user_computing',    'E100801'),
    ('CH-LT-00044',  'laptop',                'Laptop 16in',            'end_user_computing',    'E100601'),
    ('CH-DT-00110',  'desktop',               'Small form factor PC',   'end_user_computing',    'E100301'),
    ('CH-DT-00111',  'desktop',               'Small form factor PC',   'end_user_computing',    'E100501'),
    ('CH-MON-00301', 'monitor',               '27in monitor',           'end_user_computing',    'E100101'),
    ('CH-WOW-00007', 'workstation_on_wheels', 'Medication cart PC',     'clinical_device_fleet', NULL),
    ('CH-WOW-00008', 'workstation_on_wheels', 'Medication cart PC',     'clinical_device_fleet', NULL),
    ('CH-SCN-00003', 'barcode_scanner',       'Healthcare barcode scanner', 'clinical_device_fleet', NULL),
    ('CH-SCN-00004', 'barcode_scanner',       'Healthcare barcode scanner', 'clinical_device_fleet', NULL),
    ('CH-PRN-00011', 'wristband_printer',     'Wristband label printer', 'clinical_device_fleet', NULL),
    ('CH-PRN-00020', 'office_printer',        'Office laser printer',   'office_printing',       NULL),
    ('CH-PRN-00021', 'office_printer',        'Office laser printer',   'office_printing',       NULL);
