"use client";
import React, { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getCustomTemplateDetails, refreshRuntimeTemplates } from "../hooks/useCustomTemplates";
import { isRuntimeTemplate } from "../hooks/runtimeTemplates";
import { getSchemaByTemplateId, getSettingsByTemplateId } from "../presentation-templates";
const page = () => {
  const searchParams = useSearchParams();
  const templateID = searchParams.get("group");
  if (!templateID) {
    return <div>No templateID provided</div>;
  }
  const [loading, setLoading] = useState(true);
  const [layout, setLayout] = useState<any[]>([]);
  const [settings, setSettings] = useState<any>({
    description: "",
    ordered: false,
    default: false,
    icon_weight: "bold",
  });
  useEffect(() => {
    const fetchLayoutsAndSettings = async () => {
      // Learn which built-ins a data folder overrides before deciding where to look.
      await refreshRuntimeTemplates().catch(() => undefined);
      if (isRuntimeTemplate(templateID)) {
        const customTemplateDetails = await getCustomTemplateDetails(templateID, templateID, "");

        if (customTemplateDetails) {

          setLayout(customTemplateDetails.layouts.map(layout => {
            return {
              id: `${customTemplateDetails.id}:${layout.layoutId}`,
              name: layout.layoutName,
              description: layout.layoutDescription,
              json_schema: layout.schemaJSON,
            }
          }));
          setSettings({
            ...customTemplateDetails.template,
            ordered: Boolean(customTemplateDetails.template?.ordered),
            default: false,
            icon_weight: customTemplateDetails.template?.icon_weight || "bold",
          });
        }
      } else {
        const layoutsData = getSchemaByTemplateId(templateID || "");
        const settingsData = getSettingsByTemplateId(templateID || "");
        setLayout(layoutsData);
        setSettings(settingsData || {
          description: "",
          ordered: false,
          default: true,
          icon_weight: "bold",
        });

      }
      setLoading(false);

    };
    fetchLayoutsAndSettings();


  }, [templateID]);






  return (
    <div>
      {loading ? (
        <div>Loading...</div>
      ) : (
        <div>
          <div data-layouts={JSON.stringify(layout)}>
            <pre>{JSON.stringify(layout, null, 2)}</pre>\
          </div>
          <div data-settings={JSON.stringify(settings)}>
            <pre>{JSON.stringify(settings, null, 2)}</pre>
          </div>
        </div>
      )}


    </div>
  );
};

export default page;
