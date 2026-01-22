Идеи на потом:

1) Держать документацию RequestExecutorProtocol в духе no-throw (синхронизировать док/контракт).
2) Ввести прослойку SourceMapper между reader и validator: разделить физический reader (CSV/DB/API) и маппер, который приводит данные к унифицированному CsvRow.
