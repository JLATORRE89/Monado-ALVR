#define XR_USE_GRAPHICS_API_VULKAN
#define XR_USE_PLATFORM_XLIB
#include <vulkan/vulkan.h>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define XR_OK(x) do { XrResult r=(x); if(XR_FAILED(r)){fprintf(stderr,"%s failed: %d\n",#x,r); exit(1);} }while(0)
#define VK_OK(x) do { VkResult r=(x); if(r!=VK_SUCCESS){fprintf(stderr,"%s failed: %d\n",#x,r); exit(1);} }while(0)

int main(void){
 XrInstance inst=XR_NULL_HANDLE; XrInstanceCreateInfo ici={XR_TYPE_INSTANCE_CREATE_INFO};
 strcpy(ici.applicationInfo.applicationName,"Intel XR Checkerboard"); ici.applicationInfo.apiVersion=XR_CURRENT_API_VERSION;
 const char *exts[]={XR_KHR_VULKAN_ENABLE_EXTENSION_NAME}; ici.enabledExtensionCount=1; ici.enabledExtensionNames=exts; XR_OK(xrCreateInstance(&ici,&inst));
 XrSystemGetInfo sgi={XR_TYPE_SYSTEM_GET_INFO}; sgi.formFactor=XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY; XrSystemId sys; XR_OK(xrGetSystem(inst,&sgi,&sys));
 PFN_xrGetVulkanGraphicsRequirementsKHR req; XR_OK(xrGetInstanceProcAddr(inst,"xrGetVulkanGraphicsRequirementsKHR",(PFN_xrVoidFunction*)&req));
 XrGraphicsRequirementsVulkanKHR gr={XR_TYPE_GRAPHICS_REQUIREMENTS_VULKAN_KHR}; XR_OK(req(inst,sys,&gr));
 PFN_xrGetVulkanInstanceExtensionsKHR gie; PFN_xrGetVulkanDeviceExtensionsKHR gde; PFN_xrGetVulkanGraphicsDeviceKHR ggd;
 XR_OK(xrGetInstanceProcAddr(inst,"xrGetVulkanInstanceExtensionsKHR",(PFN_xrVoidFunction*)&gie));
 XR_OK(xrGetInstanceProcAddr(inst,"xrGetVulkanDeviceExtensionsKHR",(PFN_xrVoidFunction*)&gde));
 XR_OK(xrGetInstanceProcAddr(inst,"xrGetVulkanGraphicsDeviceKHR",(PFN_xrVoidFunction*)&ggd));
 uint32_t n=0; gie(inst,sys,0,&n,NULL); char *ies=calloc(1,n); gie(inst,sys,n,&n,ies);
 const char *ie[32]; uint32_t ic=0; for(char *p=strtok(ies," ");p&&ic<32;p=strtok(NULL," "))ie[ic++]=p;
 VkApplicationInfo vai={VK_STRUCTURE_TYPE_APPLICATION_INFO}; vai.apiVersion=VK_API_VERSION_1_0;
 VkInstanceCreateInfo vici={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; vici.pApplicationInfo=&vai; vici.enabledExtensionCount=ic; vici.ppEnabledExtensionNames=ie;
 VkInstance vi; VK_OK(vkCreateInstance(&vici,NULL,&vi)); VkPhysicalDevice pd; XR_OK(ggd(inst,sys,vi,&pd));
 uint32_t qn=0; vkGetPhysicalDeviceQueueFamilyProperties(pd,&qn,NULL); VkQueueFamilyProperties *qp=calloc(qn,sizeof(*qp)); vkGetPhysicalDeviceQueueFamilyProperties(pd,&qn,qp);
 uint32_t q=0; for(;q<qn;q++)if(qp[q].queueFlags&VK_QUEUE_GRAPHICS_BIT)break;
 gde(inst,sys,0,&n,NULL); char *des=calloc(1,n); gde(inst,sys,n,&n,des); const char *de[32]; uint32_t dc=0; for(char *p=strtok(des," ");p&&dc<32;p=strtok(NULL," "))de[dc++]=p;
 float pr=1; VkDeviceQueueCreateInfo qci={VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; qci.queueFamilyIndex=q;qci.queueCount=1;qci.pQueuePriorities=&pr;
 VkDeviceCreateInfo dci={VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};dci.queueCreateInfoCount=1;dci.pQueueCreateInfos=&qci;dci.enabledExtensionCount=dc;dci.ppEnabledExtensionNames=de;
 VkDevice dev; VK_OK(vkCreateDevice(pd,&dci,NULL,&dev)); VkQueue queue;vkGetDeviceQueue(dev,q,0,&queue);
 XrGraphicsBindingVulkanKHR bind={XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR};bind.instance=vi;bind.physicalDevice=pd;bind.device=dev;bind.queueFamilyIndex=q;bind.queueIndex=0;
 XrSessionCreateInfo sci={XR_TYPE_SESSION_CREATE_INFO};sci.next=&bind;sci.systemId=sys;XrSession sess;XR_OK(xrCreateSession(inst,&sci,&sess));
 uint32_t vc=0;XR_OK(xrEnumerateViewConfigurationViews(inst,sys,XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,0,&vc,NULL));XrViewConfigurationView *vv=calloc(vc,sizeof(*vv));for(uint32_t i=0;i<vc;i++)vv[i].type=XR_TYPE_VIEW_CONFIGURATION_VIEW;XR_OK(xrEnumerateViewConfigurationViews(inst,sys,XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,vc,&vc,vv));
 uint32_t fc=0;XR_OK(xrEnumerateSwapchainFormats(sess,0,&fc,NULL));int64_t *fm=calloc(fc,sizeof(*fm));XR_OK(xrEnumerateSwapchainFormats(sess,fc,&fc,fm));int64_t fmt=VK_FORMAT_R8G8B8A8_SRGB;int found=0;for(uint32_t i=0;i<fc;i++)if(fm[i]==fmt)found=1;if(!found)fmt=fm[0];
 XrSwapchain sw[2];uint32_t scn[2];XrSwapchainImageVulkanKHR *imgs[2];for(int e=0;e<2;e++){XrSwapchainCreateInfo ci={XR_TYPE_SWAPCHAIN_CREATE_INFO};ci.usageFlags=XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT|XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;ci.format=fmt;ci.sampleCount=1;ci.width=vv[e].recommendedImageRectWidth;ci.height=vv[e].recommendedImageRectHeight;ci.faceCount=1;ci.arraySize=1;ci.mipCount=1;XR_OK(xrCreateSwapchain(sess,&ci,&sw[e]));XR_OK(xrEnumerateSwapchainImages(sw[e],0,&scn[e],NULL));imgs[e]=calloc(scn[e],sizeof(**imgs));for(uint32_t i=0;i<scn[e];i++)imgs[e][i].type=XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR;XR_OK(xrEnumerateSwapchainImages(sw[e],scn[e],&scn[e],(XrSwapchainImageBaseHeader*)imgs[e]));}
 VkCommandPool pool;VkCommandPoolCreateInfo pci={VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pci.queueFamilyIndex=q;pci.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;VK_OK(vkCreateCommandPool(dev,&pci,NULL,&pool));
 XrReferenceSpaceCreateInfo rci={XR_TYPE_REFERENCE_SPACE_CREATE_INFO};rci.referenceSpaceType=XR_REFERENCE_SPACE_TYPE_LOCAL;rci.poseInReferenceSpace.orientation.w=1;XrSpace space;XR_OK(xrCreateReferenceSpace(sess,&rci,&space));
 int running=1,begun=0;int last_should_render=-1;puts("Intel XR checkerboard running: RED/GREEN left eye, BLUE/WHITE right eye.");
 while(running){XrEventDataBuffer ev={XR_TYPE_EVENT_DATA_BUFFER};while(xrPollEvent(inst,&ev)==XR_SUCCESS){if(ev.type==XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED){XrSessionState st=((XrEventDataSessionStateChanged*)&ev)->state;fprintf(stderr,"[INTEL-XR-CHECKERBOARD] SESSION_STATE=%d\n",(int)st);if(st==XR_SESSION_STATE_READY&&!begun){XrSessionBeginInfo bi={XR_TYPE_SESSION_BEGIN_INFO};bi.primaryViewConfigurationType=XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;XR_OK(xrBeginSession(sess,&bi));begun=1;}if(st==XR_SESSION_STATE_STOPPING&&begun){xrEndSession(sess);begun=0;}if(st==XR_SESSION_STATE_EXITING||st==XR_SESSION_STATE_LOSS_PENDING)running=0;}ev.type=XR_TYPE_EVENT_DATA_BUFFER;ev.next=NULL;}if(!begun)continue;
 XrFrameWaitInfo wi={XR_TYPE_FRAME_WAIT_INFO};XrFrameState fs={XR_TYPE_FRAME_STATE};XR_OK(xrWaitFrame(sess,&wi,&fs));if(last_should_render!=(int)fs.shouldRender){fprintf(stderr,"[INTEL-XR-CHECKERBOARD] SHOULD_RENDER=%d displayTime=%lld\n",(int)fs.shouldRender,(long long)fs.predictedDisplayTime);last_should_render=(int)fs.shouldRender;}XrFrameBeginInfo bi={XR_TYPE_FRAME_BEGIN_INFO};XR_OK(xrBeginFrame(sess,&bi));
 XrCompositionLayerProjectionView pv[2];memset(pv,0,sizeof(pv));XrViewLocateInfo li={XR_TYPE_VIEW_LOCATE_INFO};li.viewConfigurationType=XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;li.displayTime=fs.predictedDisplayTime;li.space=space;XrViewState vs={XR_TYPE_VIEW_STATE};XrView views[2]={{XR_TYPE_VIEW},{XR_TYPE_VIEW}};uint32_t out=0;XrResult locate_result=xrLocateViews(sess,&li,&vs,2,&out,views);if(XR_FAILED(locate_result)){fprintf(stderr,"[INTEL-XR-CHECKERBOARD] xrLocateViews failed: %d\n",locate_result);exit(1);}static int located_logged=0;if(!located_logged){fprintf(stderr,"[INTEL-XR-CHECKERBOARD] LOCATE_VIEWS count=%u flags=0x%llx\n",out,(unsigned long long)vs.viewStateFlags);located_logged=1;}
 for(int e=0;e<2;e++){uint32_t ix;XrSwapchainImageAcquireInfo ai={XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};XR_OK(xrAcquireSwapchainImage(sw[e],&ai,&ix));XrSwapchainImageWaitInfo swi={XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};swi.timeout=XR_INFINITE_DURATION;XR_OK(xrWaitSwapchainImage(sw[e],&swi));
 VkCommandBuffer cb;VkCommandBufferAllocateInfo cai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};cai.commandPool=pool;cai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;cai.commandBufferCount=1;VK_OK(vkAllocateCommandBuffers(dev,&cai,&cb));VkCommandBufferBeginInfo cbi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK_OK(vkBeginCommandBuffer(cb,&cbi));
 VkImageMemoryBarrier b={VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};b.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;b.newLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;b.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;b.image=imgs[e][ix].image;b.subresourceRange.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT;b.subresourceRange.levelCount=1;b.subresourceRange.layerCount=1;vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,NULL,0,NULL,1,&b);
 VkClearColorValue col=e==0?(VkClearColorValue){{1,0,0,1}}:(VkClearColorValue){{0,0,1,1}};VkImageSubresourceRange rg={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};vkCmdClearColorImage(cb,imgs[e][ix].image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&col,1,&rg);
 b.oldLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;b.newLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;b.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;b.dstAccessMask=VK_ACCESS_COLOR_ATTACHMENT_READ_BIT;vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,0,0,NULL,0,NULL,1,&b);VK_OK(vkEndCommandBuffer(cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&cb;VK_OK(vkQueueSubmit(queue,1,&si,VK_NULL_HANDLE));VK_OK(vkQueueWaitIdle(queue));vkFreeCommandBuffers(dev,pool,1,&cb);XrSwapchainImageReleaseInfo ri={XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};XR_OK(xrReleaseSwapchainImage(sw[e],&ri));
 pv[e].type=XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW;pv[e].pose=views[e].pose;pv[e].fov=views[e].fov;pv[e].subImage.swapchain=sw[e];pv[e].subImage.imageRect.extent.width=vv[e].recommendedImageRectWidth;pv[e].subImage.imageRect.extent.height=vv[e].recommendedImageRectHeight;}
 XrCompositionLayerProjection layer={XR_TYPE_COMPOSITION_LAYER_PROJECTION};layer.space=space;layer.viewCount=2;layer.views=pv;const XrCompositionLayerBaseHeader *layers[]={ (const XrCompositionLayerBaseHeader*)&layer};XrFrameEndInfo ei={XR_TYPE_FRAME_END_INFO};ei.displayTime=fs.predictedDisplayTime;ei.environmentBlendMode=XR_ENVIRONMENT_BLEND_MODE_OPAQUE;ei.layerCount=fs.shouldRender?1:0;ei.layers=fs.shouldRender?layers:NULL;static int submitted_logged=0;if(fs.shouldRender&&!submitted_logged){fprintf(stderr,"[INTEL-XR-CHECKERBOARD] SUBMIT_PROJECTION_LAYER views=2\n");submitted_logged=1;}XR_OK(xrEndFrame(sess,&ei));}
 return 0;
}
